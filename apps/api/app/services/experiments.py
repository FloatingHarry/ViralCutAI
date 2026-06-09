from __future__ import annotations

import json
import time
from typing import Any, TypedDict
from uuid import UUID

import httpx
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import ExperimentAnalysis, ExperimentVariant, FactorAttribution, GenerationRun
from app.schemas import ExperimentAnalyzeCreate
from app.services.agent_workflows import (
    _ark_base_url,
    _extract_json_object,
    _join_api_url,
    _provider_retry_delay_seconds,
    _public_model_label,
    _raise_for_status,
    _safe_error,
    _text_provider_configured,
)


class ExperimentGraphState(TypedDict, total=False):
    request: dict[str, Any]
    runs: list[dict[str, Any]]
    variant_metrics: dict[str, dict[str, Any]]
    result: dict[str, Any]
    trace: list[dict[str, Any]]


def create_experiment_analysis(payload: ExperimentAnalyzeCreate, db: Session) -> ExperimentAnalysis:
    metrics_by_run = _variant_metrics_by_run(payload)
    if not _text_provider_configured():
        raise ValueError("Volcengine text provider is required for real metric attribution. Connect the text provider before running Analytics.")
    runs = _load_runs(payload.run_ids, db)
    if len(runs) < 2:
        raise ValueError("At least two generation runs are required for A/B analysis.")
    run_payloads = [_run_payload(run) for run in runs]
    state = EXPERIMENT_GRAPH.invoke(
        {
            "request": payload.model_dump(mode="json"),
            "runs": run_payloads,
            "variant_metrics": metrics_by_run,
            "trace": [],
        }
    )
    result = state["result"]
    failed = any(step.get("status") == "failed" or step.get("execution_mode") == "real_failed" for step in state["trace"])
    experiment = ExperimentAnalysis(
        title=payload.title,
        status="failed" if failed else "succeeded",
        summary=result["summary"],
        winner_run_id=UUID(result["winner_run_id"]) if result.get("winner_run_id") else None,
        input_payload=payload.model_dump(mode="json"),
        result=result,
        trace=state["trace"],
    )
    db.add(experiment)
    db.flush()
    for index, variant in enumerate(result["variants"], start=1):
        db.add(
            ExperimentVariant(
                experiment_id=experiment.id,
                run_id=UUID(variant["run_id"]),
                order_index=index,
                label=variant["label"],
                metrics=variant["metrics"],
            )
        )
    for item in result["factor_attribution"]:
        db.add(
            FactorAttribution(
                experiment_id=experiment.id,
                factor_key=item["factor_key"],
                factor_name=item["factor_name"],
                category=item["category"],
                score=item["score"],
                lift=item["lift"],
                evidence=item["evidence"],
            )
        )
    db.commit()
    return get_experiment(experiment.id, db)


def list_experiments(db: Session) -> list[ExperimentAnalysis]:
    experiments = db.scalars(
        select(ExperimentAnalysis)
        .options(selectinload(ExperimentAnalysis.variants), selectinload(ExperimentAnalysis.attributions))
        .order_by(ExperimentAnalysis.created_at.desc())
    )
    return [experiment for experiment in experiments.all() if (experiment.input_payload or {}).get("variant_metrics")]


def get_experiment(experiment_id: UUID, db: Session) -> ExperimentAnalysis:
    experiment = db.scalar(
        select(ExperimentAnalysis)
        .where(ExperimentAnalysis.id == experiment_id)
        .options(selectinload(ExperimentAnalysis.variants), selectinload(ExperimentAnalysis.attributions))
    )
    if experiment is None:
        raise LookupError("Experiment analysis not found")
    experiment.attributions.sort(key=lambda item: item.score, reverse=True)
    return experiment


def _load_runs(run_ids: list[UUID], db: Session) -> list[GenerationRun]:
    runs = []
    for run_id in run_ids:
        run = db.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == run_id)
            .options(selectinload(GenerationRun.assets), selectinload(GenerationRun.artifacts))
        )
        if run:
            if run.status != "succeeded":
                raise ValueError("Only succeeded generation runs can be analyzed. Failed runs remain available in Trace Console for debugging.")
            runs.append(run)
    return runs


def _run_payload(run: GenerationRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "product_name": run.request_payload.get("product_name"),
        "summary": run.summary,
        "status": run.status,
        "viral_factors": run.viral_factors or run.strategy.get("factor_board") or run.strategy.get("selected_factors", []),
        "storyboard": run.storyboard,
        "asset_count": len(run.assets),
        "artifact_types": [artifact.artifact_type for artifact in run.artifacts],
        "compliance_passed": bool(run.compliance.get("passed")),
    }


def _variant_metrics_by_run(payload: ExperimentAnalyzeCreate) -> dict[str, dict[str, Any]]:
    if not payload.variant_metrics:
        raise ValueError("Real variant metrics are required. Enter views, watch completion, watch time, CTR, CVR, orders, and revenue for every selected run.")
    if len(payload.variant_metrics) != len(payload.run_ids):
        raise ValueError("Every selected run must have exactly one metrics row.")
    expected_ids = {str(run_id) for run_id in payload.run_ids}
    metrics_by_run: dict[str, dict[str, Any]] = {}
    for index, metric in enumerate(payload.variant_metrics, start=1):
        run_id = str(metric.run_id)
        if run_id in metrics_by_run:
            raise ValueError("Duplicate metrics were submitted for the same run.")
        data = metric.model_dump(mode="json")
        data["label"] = data.get("label") or f"Variant {chr(64 + index)}"
        metrics_by_run[run_id] = data
    if set(metrics_by_run) != expected_ids:
        raise ValueError("Metrics run IDs must match the selected generation runs.")
    return metrics_by_run


def attribution_experiment_agent(state: ExperimentGraphState) -> ExperimentGraphState:
    started = time.perf_counter()
    metric_started = time.perf_counter()
    baseline = _build_real_metric_result(state)
    substeps = [
        {
            "substep_name": "real_metric_validation",
            "status": "succeeded",
            "provider": "local_metric_validator",
            "model": "manual-real-metric-schema",
            "execution_mode": "real",
            "provider_status": "configured",
            "provider_message": "User-entered real metrics were validated and joined with run factors before LLM analysis.",
            "input_summary": {"run_count": len(state["runs"])},
            "output_summary": {"variant_count": len(baseline["variants"]), "factor_count": len(baseline["factor_attribution"])},
            "duration_ms": max(1, int((time.perf_counter() - metric_started) * 1000)),
            "error": None,
        }
    ]
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model or "volcengine-endpoint-unconfigured"
    execution_mode = "real"
    provider_status = "configured"
    provider_message = "Volcengine text provider analyzed real variant metrics and run factors."
    provider = "volcengine_ark_chat"
    public_model = _public_model_label(model, "volcengine")
    result = baseline
    insight_started = time.perf_counter()
    try:
        result = _real_experiment_result(state, baseline)
        substeps.append(
            _experiment_substep(
                "insight_summary",
                insight_started,
                provider,
                public_model,
                execution_mode,
                provider_status,
                provider_message,
                {"objective": state["request"].get("objective"), "variant_count": len(baseline["variants"])},
                {"winner": result["winner_label"], "factor_count": len(result["factor_attribution"])},
            )
        )
    except Exception as exc:
        execution_mode = "real_metric_local"
        provider_status = "json_error"
        provider_message = (
            "Volcengine returned malformed experiment analysis JSON; local real-metric attribution was used. "
            f"Reason: {_safe_error(exc)}"
        )
        result = {
            **baseline,
            "mode": "local_metric_attribution",
            "summary": (
                f"{baseline['winner_label']} leads this experiment based on user-entered real performance metrics. "
                "Provider narrative JSON was unavailable, so charts use deterministic local attribution."
            ),
            "risk_notes": [*baseline.get("risk_notes", []), provider_message],
        }
        substeps.append(
            _experiment_substep(
                "insight_summary",
                insight_started,
                provider,
                public_model,
                execution_mode,
                provider_status,
                provider_message,
                {"objective": state["request"].get("objective"), "variant_count": len(baseline["variants"])},
                {"source": "local_metric_attribution", "winner": result["winner_label"], "factor_count": len(result["factor_attribution"])},
                error=_safe_error(exc),
            )
        )
    trace = {
        "agent_name": "Attribution & Experiment Agent",
        "status": "failed" if execution_mode == "real_failed" else "succeeded",
        "provider": provider,
        "model": public_model,
        "execution_mode": execution_mode,
        "provider_status": provider_status,
        "provider_message": provider_message,
        "input": {"run_count": len(state["runs"]), "objective": state["request"].get("objective")},
        "output": {
            "winner": result["winner_label"],
            "variant_count": len(result["variants"]),
            "factor_count": len(result["factor_attribution"]),
            "substeps": substeps,
        },
        "duration_ms": max(1, int((time.perf_counter() - started) * 1000)),
        "fallback": "Provider narrative JSON failed; deterministic local attribution used the user-entered metrics."
        if execution_mode == "real_metric_local"
        else "No fallback analysis was generated because the configured real provider failed."
        if execution_mode == "real_failed"
        else provider_message
        if execution_mode != "real"
        else "Real Volcengine analysis completed over user-entered metrics.",
        "error": provider_message if execution_mode == "real_failed" else None,
    }
    return {**state, "result": result, "trace": [*state.get("trace", []), trace]}


def _build_real_metric_result(state: ExperimentGraphState) -> dict[str, Any]:
    variants = []
    factor_scores: dict[str, dict[str, Any]] = {}
    metrics_by_run = state.get("variant_metrics", {})
    for index, run in enumerate(state["runs"], start=1):
        raw_metrics = metrics_by_run.get(run["run_id"])
        if not raw_metrics:
            raise ValueError("Every run needs real metrics before attribution can run.")
        metrics = _normalize_real_metrics(raw_metrics)
        variants.append(
            {
                "run_id": run["run_id"],
                "label": str(raw_metrics.get("label") or f"Variant {chr(64 + index)}"),
                "product_name": run["product_name"],
                "metrics": metrics,
            }
        )
    average_score = sum(float(variant["metrics"]["analysis_score"]) for variant in variants) / max(1, len(variants))
    for variant in variants:
        run = next(item for item in state["runs"] if item["run_id"] == variant["run_id"])
        metrics = variant["metrics"]
        for factor in run.get("viral_factors", []):
            key = factor.get("factor_key") or factor.get("id") or factor.get("name")
            current = factor_scores.setdefault(
                key,
                {
                    "factor_key": key,
                    "factor_name": factor.get("name", key),
                    "category": factor.get("category", "factor"),
                    "score": 0,
                    "lift": 0,
                    "evidence": [],
                },
            )
            score = float(metrics["analysis_score"]) * (float(factor.get("confidence", 70)) / 100)
            current["score"] += int(round(score))
            current["lift"] += int(round(float(metrics["analysis_score"]) - average_score))
            current["evidence"].append(
                f"{run['product_name']}: {factor.get('reason', 'factor used')} "
                f"Real metrics: {metrics['watch_completion_rate']}% completion, {metrics['ctr']}% CTR, {metrics['cvr']}% CVR."
            )
    winner = max(variants, key=lambda item: item["metrics"]["analysis_score"])
    factor_attribution = [
        {
            "factor_key": value["factor_key"],
            "factor_name": value["factor_name"],
            "category": value["category"],
            "score": min(100, value["score"]),
            "lift": value["lift"],
            "evidence": value["evidence"][0],
        }
        for value in sorted(factor_scores.values(), key=lambda item: item["score"], reverse=True)
    ][:8]
    result = {
        "mode": "real_metric_attribution",
        "summary": f"{winner['label']} leads this experiment based on user-entered real performance metrics.",
        "winner_run_id": winner["run_id"],
        "winner_label": winner["label"],
        "variants": variants,
        "factor_attribution": factor_attribution,
        "next_iteration_recommendation": {
            "keep": [item["factor_name"] for item in factor_attribution[:3]],
            "change": "Generate a new variant that preserves the winning factor stack while testing one sharper proof shot and CTA.",
            "prompt_hint": "Ask the Viral Strategy Agent to keep the winning hook and vary proof density, offer framing, or CTA timing.",
        },
        "risk_notes": [
            "Metrics were manually entered by the user from real campaign or platform data.",
            "No synthetic experiment metrics were generated by ViralCutAI.",
        ],
    }
    return result


def _normalize_real_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    views = max(1, int(raw.get("views") or 0))
    completion = _clamp_float(raw.get("watch_completion_rate"), 0, 100)
    avg_watch = _clamp_float(raw.get("avg_watch_seconds"), 0, 12)
    ctr = _clamp_float(raw.get("ctr"), 0, 100)
    cvr = _clamp_float(raw.get("cvr"), 0, 100)
    orders = max(0, int(raw.get("orders") or 0))
    revenue = max(0.0, float(raw.get("revenue") or 0))
    orders_per_1000 = orders / views * 1000
    revenue_per_1000 = revenue / views * 1000
    watch_score = (avg_watch / 12) * 100
    analysis_score = min(
        100,
        round(
            completion * 0.28
            + watch_score * 0.22
            + ctr * 1.2
            + cvr * 2.2
            + min(orders_per_1000 * 1.5, 18)
            + min(revenue_per_1000 / 4, 12),
            2,
        ),
    )
    return {
        "views": views,
        "watch_completion_rate": round(completion, 2),
        "avg_watch_seconds": round(avg_watch, 2),
        "ctr": round(ctr, 2),
        "cvr": round(cvr, 2),
        "orders": orders,
        "revenue": round(revenue, 2),
        "orders_per_1000_views": round(orders_per_1000, 2),
        "revenue_per_1000_views": round(revenue_per_1000, 2),
        "analysis_score": analysis_score,
        "source": "manual_real_metrics",
    }


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))


def _real_experiment_result(state: ExperimentGraphState, baseline: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model
    base_url = _ark_base_url(settings.volcengine_base_url)
    url = _join_api_url(base_url, "/chat/completions")
    prompt = {
        "objective": state["request"].get("objective"),
        "variants": baseline["variants"],
        "factor_attribution": baseline["factor_attribution"][:8],
        "risk_notes": baseline["risk_notes"],
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are ViralCutAI's experiment analysis agent. Return exactly one minified JSON object only. "
                    "No markdown, no comments, no trailing commas, no newlines inside string values. "
                    "Analyze user-entered real performance metrics and generation factors in English. "
                    "Do not invent or change numeric metrics."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return JSON with exactly these top-level keys: summary, winner_run_id, winner_label, variants, "
                    "factor_attribution, next_iteration_recommendation, risk_notes. "
                    "Keep strings concise. Keep factor_attribution length <= 8. "
                    "Keep run_ids unchanged and do not invent API keys or private data.\n\n"
                    f"INPUT JSON:\n{json.dumps(prompt, ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1400,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {settings.volcengine_api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
                if response.status_code == 400:
                    retry_body = {key: value for key, value in body.items() if key not in {"response_format", "thinking"}}
                    response = client.post(url, headers=headers, json=retry_body)
                _raise_for_status(response, "Volcengine experiment analysis")
            break
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(_provider_retry_delay_seconds(exc, attempt))
    if last_error is not None and "response" not in locals():
        raise last_error
    content = response.json()["choices"][0]["message"]["content"]
    try:
        parsed = _extract_json_object(content)
    except Exception as exc:
        parsed = _repair_experiment_json(content, exc)
    return _normalize_experiment_result(parsed, baseline)


def _experiment_substep(
    substep_name: str,
    started_at: float,
    provider: str,
    model: str,
    execution_mode: str,
    provider_status: str,
    provider_message: str,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    status: str = "succeeded",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "substep_name": substep_name,
        "status": status,
        "provider": provider,
        "model": model,
        "execution_mode": execution_mode,
        "provider_status": provider_status,
        "provider_message": provider_message,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "duration_ms": max(1, int((time.perf_counter() - started_at) * 1000)),
        "error": error,
    }


def _repair_experiment_json(broken_content: str, parse_error: Exception) -> dict[str, Any]:
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model
    base_url = _ark_base_url(settings.volcengine_base_url)
    url = _join_api_url(base_url, "/chat/completions")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Repair malformed JSON. Return one minified valid JSON object only, no markdown."},
            {
                "role": "user",
                "content": (
                    f"Parse error: {_safe_error(parse_error)}\n"
                    "Fix this experiment analysis JSON without inventing new run IDs. "
                    "Use exactly these top-level keys if present: summary, winner_run_id, winner_label, variants, "
                    "factor_attribution, next_iteration_recommendation, risk_notes.\n\n"
                    f"BROKEN JSON/TEXT:\n{broken_content[:10000]}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 1600,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {settings.volcengine_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
        response = client.post(url, headers=headers, json=body)
        if response.status_code == 400:
            retry_body = {key: value for key, value in body.items() if key not in {"response_format", "thinking"}}
            response = client.post(url, headers=headers, json=retry_body)
        _raise_for_status(response, "Volcengine experiment JSON repair")
    return _extract_json_object(response.json()["choices"][0]["message"]["content"])


def _normalize_experiment_result(parsed: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    result = {**baseline}
    for key in ["summary", "winner_run_id", "winner_label", "next_iteration_recommendation", "risk_notes"]:
        if parsed.get(key):
            result[key] = parsed[key]
    if isinstance(parsed.get("variants"), list) and parsed["variants"]:
        result["variants"] = _merge_variants(parsed["variants"], baseline["variants"])
    if isinstance(parsed.get("factor_attribution"), list) and parsed["factor_attribution"]:
        result["factor_attribution"] = _merge_attributions(parsed["factor_attribution"], baseline["factor_attribution"])
    if not any(variant["run_id"] == result.get("winner_run_id") for variant in result["variants"]):
        result["winner_run_id"] = baseline["winner_run_id"]
        result["winner_label"] = baseline["winner_label"]
    return result


def _merge_variants(provider_variants: list[dict[str, Any]], baseline_variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_by_run = {variant["run_id"]: variant for variant in baseline_variants}
    merged = []
    for provider_variant in provider_variants:
        run_id = str(provider_variant.get("run_id") or "")
        base = baseline_by_run.get(run_id)
        if not base:
            continue
        merged.append(
            {
                **base,
                "label": str(provider_variant.get("label") or base["label"]),
                "metrics": base["metrics"],
            }
        )
    return merged or baseline_variants


def _merge_attributions(provider_items: list[dict[str, Any]], baseline_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_by_key = {item["factor_key"]: item for item in baseline_items}
    merged = []
    for provider_item in provider_items[:8]:
        key = str(provider_item.get("factor_key") or "")
        base = baseline_by_key.get(key)
        if not base:
            continue
        merged.append(
            {
                **base,
                "factor_name": str(provider_item.get("factor_name") or base["factor_name"]),
                "category": str(provider_item.get("category") or base["category"]),
                "evidence": str(provider_item.get("evidence") or base["evidence"]),
            }
        )
    return merged or baseline_items


def _build_experiment_graph():
    graph = StateGraph(ExperimentGraphState)
    graph.add_node("attribution_experiment", attribution_experiment_agent)
    graph.set_entry_point("attribution_experiment")
    graph.add_edge("attribution_experiment", END)
    return graph.compile()


EXPERIMENT_GRAPH = _build_experiment_graph()
