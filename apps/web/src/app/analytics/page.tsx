"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, Loader2, RefreshCcw, Sparkles, Trophy } from "lucide-react";

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
  const metricsReady = selectedRunIds.length >= 2 && selectedRunIds.length <= 4 && selectedRunIds.every((id) => isMetricFormValid(metrics[id]));

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

  async function runAnalysis() {
    if (!metricsReady) {
      setError("Enter real metrics for every selected run before running attribution.");
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
        eyebrow="Experiment Lab"
        title="Analyze real metrics from generated variants"
        description="Select two to four succeeded Studio runs, enter real campaign metrics, then run the Attribution Agent. No simulated A/B data is generated."
        badges={["POST /experiments/analyze", "manual metrics", "Attribution Agent"]}
      />

      <section className="grid gap-4 md:grid-cols-5">
        <StatCard label="Runs" value={String(succeededRuns.length)} detail="Succeeded candidate variants." />
        <StatCard label="Experiments" value={String(experiments.length)} detail="Real metric analyses." />
        <StatCard label="Factors" value={String(factorCount)} detail="Generated factor snapshots." />
        <StatCard label="Selected" value={`${selectedRunIds.length}/4`} detail="A/B variants." />
        <StatCard label="Winner" value={latestExperiment?.result.winner_label ?? "-"} detail="Latest analysis." />
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="xl:sticky xl:top-24 xl:self-start">
          <CardHeader>
            <div>
              <CardTitle>Variant picker</CardTitle>
              <CardDescription>Choose two to four succeeded generation runs.</CardDescription>
            </div>
            <Button size="icon" variant="outline" onClick={refresh} disabled={loading} aria-label="Refresh experiment data">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            </Button>
          </CardHeader>
          <div className="space-y-3">
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

        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Real metric inputs</CardTitle>
                <CardDescription>Use data from your shop, ad account, or publishing platform. All fields are required.</CardDescription>
              </div>
              <Sparkles className="h-5 w-5 text-blue-600" />
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
                <p className="text-xs leading-5 text-slate-500">
                  Analytics only runs after real metrics are entered for every selected variant.
                </p>
                <Button variant="secondary" onClick={runAnalysis} disabled={!metricsReady || analyzing}>
                  {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Run Attribution Agent
                </Button>
              </div>
              {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Latest analysis</CardTitle>
                <CardDescription>{latestExperiment?.summary ?? "Run an experiment to see winner, lift, and next iteration advice."}</CardDescription>
              </div>
              <Trophy className="h-5 w-5 text-amber-600" />
            </CardHeader>
            {latestExperiment ? (
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
                <div className="grid gap-3">
                  {latestExperiment.variants.map((variant) => (
                    <div key={variant.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-slate-950">{variant.label}</p>
                        <Badge className={variant.run_id === latestExperiment.winner_run_id ? "border-amber-200 bg-amber-50 text-amber-700" : ""}>
                          {variant.run_id === latestExperiment.winner_run_id ? "winner" : "variant"}
                        </Badge>
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-5">
                        {Object.entries(variant.metrics)
                          .filter(([key]) => key !== "source")
                          .map(([key, value]) => (
                            <div key={key} className="rounded-md bg-white p-3">
                              <p className="text-[11px] text-slate-500">{key.replaceAll("_", " ")}</p>
                              <p className="mt-1 break-words font-mono text-sm text-slate-950">{String(value)}</p>
                            </div>
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                  <p className="text-sm font-medium text-slate-950">Next iteration</p>
                  <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-blue-900">
                    {JSON.stringify(latestExperiment.result.next_iteration_recommendation, null, 2)}
                  </pre>
                </div>
              </div>
            ) : (
              <Empty text="No experiment result yet." />
            )}
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Factor attribution</CardTitle>
                <CardDescription>Attribution uses real metrics plus factors, storyboard decisions, and artifacts from each selected run.</CardDescription>
              </div>
              <BarChart3 className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-2">
              {(latestExperiment?.attributions ?? []).map((factor) => (
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
                  <p className="mt-3 text-xs leading-5 text-slate-500">{factor.evidence}</p>
                </div>
              ))}
              {!latestExperiment ? <Empty text="Attribution will appear after analysis." /> : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Analysis Agent trace</CardTitle>
                <CardDescription>Trace comes from the Experiment Analysis Graph.</CardDescription>
              </div>
              <Sparkles className="h-5 w-5 text-cyan-700" />
            </CardHeader>
            <div className="grid gap-3">
              {(latestExperiment?.trace ?? []).map((step) => (
                <div key={`${step.agent_name}-${step.duration_ms}`} className="rounded-lg border border-black/10 bg-slate-950 p-4 text-white">
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
          </Card>
        </div>
      </section>
    </>
  );
}

function isMetricFormValid(form?: MetricForm) {
  if (!form) {
    return false;
  }
  return metricFields.every((field) => {
    const value = Number(form[field.key]);
    if (!Number.isFinite(value)) {
      return false;
    }
    if (value < field.min) {
      return false;
    }
    if (typeof field.max === "number" && value > field.max) {
      return false;
    }
    return true;
  });
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

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}
