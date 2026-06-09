"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, Loader2, RefreshCcw, Scissors, Sparkles, Trophy } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { ProviderTruthBadge } from "@/components/provider-truth";
import { StatCard } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  analyzeExperiment,
  listExperiments,
  listGenerationRuns,
  type ExperimentAnalysis,
  type ExperimentVariantMetricsInput,
  type GenerationRun,
} from "@/lib/api";

type MetricForm = {
  views: string;
  watch_completion_rate: string;
  avg_watch_seconds: string;
  ctr: string;
  cvr: string;
  orders: string;
  revenue: string;
};

const emptyMetrics: MetricForm = {
  views: "",
  watch_completion_rate: "",
  avg_watch_seconds: "",
  ctr: "",
  cvr: "",
  orders: "",
  revenue: "",
};

const metricFields: Array<{ key: keyof MetricForm; label: string; suffix?: string; min: number; max?: number; step?: string }> = [
  { key: "views", label: "Views", min: 1, step: "1" },
  { key: "watch_completion_rate", label: "Watch completion", suffix: "%", min: 0, max: 100, step: "0.1" },
  { key: "avg_watch_seconds", label: "Avg watch seconds", suffix: "s", min: 0, max: 12, step: "0.1" },
  { key: "ctr", label: "CTR", suffix: "%", min: 0, max: 100, step: "0.1" },
  { key: "cvr", label: "CVR", suffix: "%", min: 0, max: 100, step: "0.1" },
  { key: "orders", label: "Orders", min: 0, step: "1" },
  { key: "revenue", label: "Revenue", min: 0, step: "0.01" },
];

export default function AnalyticsPage() {
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [experiments, setExperiments] = useState<ExperimentAnalysis[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<Record<string, MetricForm>>({});
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latestExperiment = experiments[0] ?? null;
  const succeededRuns = useMemo(() => runs.filter((run) => run.status === "succeeded"), [runs]);
  const factorCount = useMemo(() => succeededRuns.reduce((sum, run) => sum + run.viral_factors.length, 0), [succeededRuns]);
  const selectedRuns = useMemo(
    () => selectedRunIds.map((id) => succeededRuns.find((run) => run.run_id === id)).filter(Boolean) as GenerationRun[],
    [selectedRunIds, succeededRuns],
  );
  const metricsIssue = useMemo(() => getMetricsIssue(selectedRunIds, metrics, succeededRuns), [selectedRunIds, metrics, succeededRuns]);
  const metricsReady = !metricsIssue;

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [nextRuns, nextExperiments] = await Promise.all([listGenerationRuns(), listExperiments()]);
      setRuns(nextRuns);
      setExperiments(nextExperiments);
      setSelectedRunIds((current) => current.filter((id) => nextRuns.some((run) => run.run_id === id && run.status === "succeeded")));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load experiment lab");
    } finally {
      setLoading(false);
    }
  }

  function selectLatestRun() {
    const latestRun = succeededRuns[0];
    if (!latestRun) {
      return;
    }
    setSelectedRunIds([latestRun.run_id]);
    setMetrics((current) => ({
      ...current,
      [latestRun.run_id]: current[latestRun.run_id] ?? { ...emptyMetrics },
    }));
  }

  async function runAnalysis() {
    if (metricsIssue) {
      setError(metricsIssue);
      return;
    }
    setAnalyzing(true);
    setError(null);
    try {
      await analyzeExperiment({
        title: "Real metrics factor attribution",
        run_ids: selectedRunIds,
        objective: "Compare real campaign metrics, viral factors, storyboard decisions, and next-generation direction.",
        variant_metrics: selectedRunIds.map((runId, index) => toMetricPayload(runId, metrics[runId], index)),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Attribution Agent failed");
    } finally {
      setAnalyzing(false);
    }
  }

  function toggleRun(id: string, checked: boolean) {
    setSelectedRunIds((current) => {
      const next = checked ? [...current, id].slice(0, 4) : current.filter((item) => item !== id);
      setMetrics((currentMetrics) => {
        const updated = { ...currentMetrics };
        if (checked && !updated[id]) {
          updated[id] = { ...emptyMetrics };
        }
        return updated;
      });
      return next;
    });
  }

  function updateMetric(runId: string, key: keyof MetricForm, value: string) {
    setMetrics((current) => ({
      ...current,
      [runId]: {
        ...(current[runId] ?? emptyMetrics),
        [key]: value,
      },
    }));
  }

  return (
    <>
      <PageHeader
        eyebrow="Step 5 / Analyze"
        title="Analyze real performance metrics"
        description="Select two to four succeeded Studio runs, enter real campaign metrics, then run the Attribution Agent. No simulated A/B data is generated."
        badges={["POST /experiments/analyze", "manual metrics", "Attribution Agent"]}
      />

      <section className="mb-6 rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950">Review metrics, then iterate the edit</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Pick the latest generated run for metrics, or return to Editor when the assembled cut needs another pass.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={selectLatestRun} disabled={!succeededRuns.length}>
              Select latest run
            </Button>
            <Link href="/editor">
              <Button variant="secondary">
                <Scissors className="h-4 w-4" />
                Back to editor
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-5">
        <StatCard label="Runs" value={String(succeededRuns.length)} detail="Succeeded candidate variants." />
        <StatCard label="Experiments" value={String(experiments.length)} detail="Real metric analyses." />
        <StatCard label="Factors" value={String(factorCount)} detail="Generated factor snapshots." />
        <StatCard label="Selected" value={`${selectedRunIds.length}/4`} detail="A/B variants." />
        <StatCard label="Top performer" value={latestExperiment?.result.winner_label ?? "-"} detail="Latest attribution result." />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="p-4 xl:sticky xl:top-32 xl:self-start">
          <CardHeader className="mb-3">
            <div>
              <CardTitle>Variant picker</CardTitle>
              <CardDescription>Choose two to four succeeded generation runs.</CardDescription>
            </div>
            <Button size="icon" variant="outline" onClick={refresh} disabled={loading} aria-label="Refresh experiment data">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            </Button>
          </CardHeader>
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-black/10 bg-white p-3">
              <p className="text-xs leading-5 text-slate-500">Use the newest successful run as a starting point, then add more variants for attribution.</p>
              <Button size="sm" variant="outline" onClick={selectLatestRun} disabled={!succeededRuns.length}>
                Select latest run
              </Button>
            </div>
            {runs.map((run) => {
              const disabledByStatus = run.status !== "succeeded";
              const disabledByLimit = !selectedRunIds.includes(run.run_id) && selectedRunIds.length >= 4;
              return (
                <label key={run.run_id} className="block rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={selectedRunIds.includes(run.run_id)}
                      disabled={disabledByStatus || disabledByLimit}
                      onChange={(event) => toggleRun(run.run_id, event.target.checked)}
                    />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-950">{run.request_payload.product_name}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{run.summary}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Badge className={run.status === "failed" ? "border-rose-200 bg-rose-50 text-rose-700" : ""}>{run.status}</Badge>
                    {run.viral_factors.slice(0, 3).map((factor) => (
                      <Badge key={factor.factor_key}>{factor.category}</Badge>
                    ))}
                  </div>
                </label>
              );
            })}
            {!runs.length ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm leading-6 text-slate-500">
                No runs yet. Create variants in <Link className="text-blue-600" href="/studio">Studio</Link>.
              </div>
            ) : null}
          </div>
        </Card>

        <div className="grid gap-4">
          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Real metric inputs</CardTitle>
                <CardDescription>Use data from your shop, ad account, or publishing platform. All fields are required.</CardDescription>
              </div>
            </CardHeader>
            <div className="grid gap-4">
              {selectedRuns.map((run, index) => (
                <div key={run.run_id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-slate-950">Variant {String.fromCharCode(65 + index)}</p>
                      <p className="mt-1 text-xs text-slate-500">{run.request_payload.product_name}</p>
                    </div>
                    <Badge>{run.storyboard.length} shots</Badge>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {metricFields.map((field) => (
                      <label key={`${run.run_id}-${field.key}`} className="block text-xs text-slate-600">
                        {field.label}
                        <div className="mt-1 flex items-center rounded-md border border-black/10 bg-white px-2 focus-within:border-blue-400 focus-within:ring-4 focus-within:ring-blue-100">
                          <input
                            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-slate-950 outline-none"
                            min={field.min}
                            max={field.max}
                            step={field.step}
                            type="number"
                            value={(metrics[run.run_id] ?? emptyMetrics)[field.key]}
                            onChange={(event) => updateMetric(run.run_id, field.key, event.target.value)}
                          />
                          {field.suffix ? <span className="pl-2 text-xs text-slate-400">{field.suffix}</span> : null}
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
              {!selectedRuns.length ? <Empty text="Select succeeded runs to enter metrics." /> : null}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className={`text-xs leading-5 ${metricsIssue ? "text-amber-700" : "text-slate-500"}`}>
                  {metricsIssue ?? "Ready to analyze the selected variants with real metrics."}
                </p>
                <Button variant="secondary" onClick={runAnalysis} disabled={!metricsReady || analyzing}>
                  {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Run Attribution Agent
                </Button>
              </div>
              {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
            </div>
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Latest analysis</CardTitle>
                <CardDescription>{latestExperiment?.summary ?? "Run an experiment to see the top performer, lift, and next iteration advice."}</CardDescription>
              </div>
              <Trophy className="h-5 w-5 text-amber-600" />
            </CardHeader>
            {latestExperiment ? (
              <div className="grid gap-4">
                <ExperimentCharts experiment={latestExperiment} />
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                  <div className="grid gap-3">
                    {latestExperiment.variants.map((variant) => (
                      <div key={variant.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="font-medium text-slate-950">{variant.label}</p>
                          <Badge className={variant.run_id === latestExperiment.winner_run_id ? "border-amber-200 bg-amber-50 text-amber-700" : ""}>
                            {variant.run_id === latestExperiment.winner_run_id ? "top performer" : "variant"}
                          </Badge>
                        </div>
                        <div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-5">
                          {Object.entries(variant.metrics)
                            .filter(([key]) => key !== "source")
                            .map(([key, value]) => (
                              <div key={key} className="rounded-md bg-white p-3">
                                <p className="text-[11px] text-slate-500">{key.replaceAll("_", " ")}</p>
                                <p className="mt-1 break-words font-mono text-sm text-slate-950">{formatMetricValue(value)}</p>
                              </div>
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  <NextIterationCard recommendation={latestExperiment.result.next_iteration_recommendation} />
                </div>
              </div>
            ) : (
              <Empty text="No experiment result yet." />
            )}
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Factor attribution</CardTitle>
                <CardDescription>Factor impact ranked by the selected variant metrics.</CardDescription>
              </div>
              <BarChart3 className="h-5 w-5 text-blue-600" />
            </CardHeader>
            {latestExperiment ? (
              <div className="grid gap-4">
                <FactorAttributionChart experiment={latestExperiment} />
                <div className="grid gap-3 md:grid-cols-2">
                  {latestExperiment.attributions.slice(0, 4).map((factor) => (
                    <div key={factor.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-slate-950">{factor.factor_name}</p>
                        <Badge>{factor.category}</Badge>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        <div className="rounded-md bg-white p-3">
                          <p className="text-[11px] text-slate-500">score</p>
                          <p className="font-mono text-sm text-slate-950">{factor.score}</p>
                        </div>
                        <div className="rounded-md bg-white p-3">
                          <p className="text-[11px] text-slate-500">lift</p>
                          <p className="font-mono text-sm text-slate-950">{factor.lift}</p>
                        </div>
                      </div>
                      <p className="mt-3 line-clamp-3 text-xs leading-5 text-slate-500">{factor.evidence}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <Empty text="Attribution will appear after analysis." />
            )}
          </Card>

          <details open className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-slate-950">
              Analysis Agent trace
              <Sparkles className="h-5 w-5 text-cyan-700" />
            </summary>
            <p className="mt-1 text-xs leading-5 text-slate-500">Trace comes from the Experiment Analysis Graph.</p>
            <div className="grid gap-3">
              {(latestExperiment?.trace ?? []).map((step, index) => (
                <div key={`${step.agent_name}-${step.duration_ms}-${index}`} className="rounded-lg border border-black/10 bg-slate-950 p-4 text-white">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">{step.agent_name}</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <ProviderTruthBadge mode={step.execution_mode} />
                      <Badge>{step.duration_ms}ms</Badge>
                    </div>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-white/70">{step.provider_message}</p>
                  <p className="mt-2 text-xs leading-5 text-white/60">{step.fallback}</p>
                </div>
              ))}
              {!latestExperiment ? <Empty text="No analysis trace yet." /> : null}
            </div>
          </details>
        </div>
      </section>
    </>
  );
}

function toMetricPayload(runId: string, form: MetricForm, index: number): ExperimentVariantMetricsInput {
  return {
    run_id: runId,
    label: `Variant ${String.fromCharCode(65 + index)}`,
    views: Number(form.views),
    watch_completion_rate: Number(form.watch_completion_rate),
    avg_watch_seconds: Number(form.avg_watch_seconds),
    ctr: Number(form.ctr),
    cvr: Number(form.cvr),
    orders: Number(form.orders),
    revenue: Number(form.revenue),
  };
}

function getMetricsIssue(selectedRunIds: string[], metrics: Record<string, MetricForm>, succeededRuns: GenerationRun[]) {
  if (selectedRunIds.length < 2) {
    return "Select at least two succeeded runs.";
  }
  if (selectedRunIds.length > 4) {
    return "Select no more than four variants.";
  }
  const succeededIds = new Set(succeededRuns.map((run) => run.run_id));
  const invalidRunId = selectedRunIds.find((id) => !succeededIds.has(id));
  if (invalidRunId) {
    return "Only succeeded runs can be analyzed. Refresh the page and select again.";
  }
  for (const [index, runId] of selectedRunIds.entries()) {
    const form = metrics[runId];
    const label = `Variant ${String.fromCharCode(65 + index)}`;
    if (!form) {
      return `${label}: enter all metric fields.`;
    }
    for (const field of metricFields) {
      const rawValue = form[field.key].trim();
      if (!rawValue) {
        return `${label}: enter ${field.label}.`;
      }
      const value = Number(rawValue);
      if (!Number.isFinite(value)) {
        return `${label}: ${field.label} must be a number.`;
      }
      if (value < field.min) {
        return `${label}: ${field.label} must be at least ${field.min}${field.suffix ?? ""}.`;
      }
      if (typeof field.max === "number" && value > field.max) {
        return `${label}: ${field.label} must be ${field.max}${field.suffix ?? ""} or less.`;
      }
    }
  }
  return null;
}

function ExperimentCharts({ experiment }: { experiment: ExperimentAnalysis }) {
  const chartMetrics = [
    { key: "analysis_score", title: "Overall score" },
    { key: "watch_completion_rate", title: "Watch completion", suffix: "%" },
    { key: "ctr", title: "CTR", suffix: "%" },
    { key: "revenue_per_1000_views", title: "Revenue / 1k views" },
  ];
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {chartMetrics.map((chart) => (
        <MetricDonut
          key={chart.key}
          rows={experiment.variants.map((variant) => ({
            label: variant.label,
            value: metricNumber(variant.metrics, chart.key),
            suffix: chart.suffix,
            highlight: variant.run_id === experiment.winner_run_id,
          }))}
          title={chart.title}
        />
      ))}
    </div>
  );
}

function MetricDonut({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: number; suffix?: string; highlight?: boolean }>;
}) {
  const total = Math.max(1, rows.reduce((sum, row) => sum + Math.max(0, row.value), 0));
  const highlighted = rows.find((row) => row.highlight) ?? rows[0];
  const share = Math.round((Math.max(0, highlighted?.value ?? 0) / total) * 100);
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
      <div className="flex items-center gap-4">
        <div
          className="grid h-20 w-20 shrink-0 place-items-center rounded-full"
          style={{ background: `conic-gradient(#f59e0b 0 ${share}%, #dbeafe ${share}% 100%)` }}
        >
          <div className="grid h-14 w-14 place-items-center rounded-full bg-white text-sm font-semibold text-slate-950">{share}%</div>
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950">{title}</p>
          <p className="mt-1 truncate text-xs text-slate-500">{highlighted?.label ?? "Top performer"} share</p>
          <p className="mt-2 font-mono text-sm text-slate-950">
            {formatNumber(highlighted?.value ?? 0)}
            {highlighted?.suffix ?? ""}
          </p>
        </div>
      </div>
    </div>
  );
}

function FactorAttributionChart({ experiment }: { experiment: ExperimentAnalysis }) {
  const factors = experiment.attributions.slice(0, 8);
  if (!factors.length) {
    return <Empty text="No factor attribution was returned for this analysis." />;
  }
  const categoryRows = Array.from(
    factors.reduce((map, factor) => {
      const category = factor.category || "other";
      map.set(category, (map.get(category) ?? 0) + Math.max(0, Number(factor.score) || 0));
      return map;
    }, new Map<string, number>()),
  ).sort((a, b) => b[1] - a[1]);
  const total = Math.max(1, categoryRows.reduce((sum, [, value]) => sum + value, 0));
  const colors = ["#2563eb", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#64748b"];
  const gradient = categoryRows
    .reduce<{ parts: string[]; cursor: number }>(
      (state, [, value], index) => {
        const start = state.cursor;
        const end = start + (value / total) * 100;
        return {
          cursor: end,
          parts: [...state.parts, `${colors[index % colors.length]} ${start}% ${end}%`],
        };
      },
      { parts: [], cursor: 0 },
    )
    .parts.join(", ");
  return (
    <div className="grid gap-4 rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      <div className="grid place-items-center">
        <div className="grid h-40 w-40 place-items-center rounded-full" style={{ background: `conic-gradient(${gradient})` }}>
          <div className="grid h-24 w-24 place-items-center rounded-full bg-white text-center">
            <span className="text-xs text-slate-500">Factor mix</span>
          </div>
        </div>
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-950">Factor impact by category</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {categoryRows.map(([category, value], index) => (
            <div key={category} className="flex items-center justify-between gap-3 rounded-md bg-white p-3 text-xs">
              <span className="flex min-w-0 items-center gap-2 font-medium text-slate-700">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[index % colors.length] }} />
                <span className="truncate">{category}</span>
              </span>
              <span className="font-mono text-slate-950">{Math.round((value / total) * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function NextIterationCard({ recommendation }: { recommendation?: Record<string, unknown> | string }) {
  if (typeof recommendation === "string" && recommendation.trim()) {
    return (
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
        <p className="text-sm font-medium text-slate-950">Next iteration</p>
        <p className="mt-3 text-xs leading-5 text-blue-900">{recommendation}</p>
      </div>
    );
  }
  const recommendationObject = typeof recommendation === "object" && recommendation !== null ? recommendation : undefined;
  const keep = Array.isArray(recommendationObject?.keep) ? recommendationObject.keep.map(String).filter(Boolean) : [];
  const change = typeof recommendationObject?.change === "string" ? recommendationObject.change : "";
  const promptHint = typeof recommendationObject?.prompt_hint === "string" ? recommendationObject.prompt_hint : "";
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
      <p className="text-sm font-medium text-slate-950">Next iteration</p>
      {keep.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {keep.map((item) => (
            <Badge key={item} className="border-blue-200 bg-white text-blue-700">
              Keep {item}
            </Badge>
          ))}
        </div>
      ) : null}
      {change ? <p className="mt-3 text-xs leading-5 text-blue-900">{change}</p> : null}
      {promptHint ? <p className="mt-3 rounded-md bg-white p-3 text-xs leading-5 text-slate-600">{promptHint}</p> : null}
      {!keep.length && !change && !promptHint ? <p className="mt-3 text-xs leading-5 text-blue-900">No recommendation returned.</p> : null}
    </div>
  );
}

function metricNumber(metrics: Record<string, number | boolean | string>, key: string) {
  const value = metrics[key];
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatMetricValue(value: number | boolean | string) {
  if (typeof value === "number") {
    return formatNumber(value);
  }
  return String(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}
