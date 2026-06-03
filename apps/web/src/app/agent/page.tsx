"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { GitBranch, Loader2, RefreshCcw, SearchCode } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { ProviderTruthBadge, artifactProviderMode, humanizeProviderText, providerTruthText } from "@/components/provider-truth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getGenerationRun, listExperiments, listGenerationRuns, type AgentSubstep, type ExperimentAnalysis, type GenerationRun, type MediaArtifact } from "@/lib/api";

function getSubsteps(output: Record<string, unknown>): AgentSubstep[] {
  return Array.isArray(output.substeps) ? (output.substeps as AgentSubstep[]) : [];
}

function displayJson(value: unknown) {
  return JSON.stringify(
    value,
    (key, item) => {
      if (item === "mock_missing_config") {
        return "not_connected";
      }
      if (typeof item === "string") {
        return humanizeProviderText(item);
      }
      if (key === "mock_reason") {
        return humanizeProviderText(item);
      }
      return item;
    },
    2,
  );
}

function displayArtifactTitle(artifact: MediaArtifact) {
  if (artifact.artifact_type === "cover_image_mock") {
    return "Cover image not generated";
  }
  if (artifact.artifact_type === "cover_image_failed") {
    return "Cover image failed";
  }
  if (artifact.artifact_type === "image_text_plan" || artifact.artifact_type === "image_mock") {
    return "Image prompt plan";
  }
  if (artifact.artifact_type === "video_mock") {
    return "Video provider not connected";
  }
  if (artifact.artifact_type === "video_failed") {
    return "Video provider failed";
  }
  if (artifact.artifact_type === "seedance_draft_video") {
    return "Seedance continuous draft";
  }
  if (artifact.artifact_type === "seedance_replacement_clip") {
    return "Seedance replacement segment";
  }
  if (artifact.artifact_type === "seedance_shot_clip") {
    return "Legacy Seedance shot clip";
  }
  return artifact.title.replaceAll("_", " ").replace(/\bmock\b/gi, "plan");
}

const activeStatuses = new Set(["queued", "running", "pending", "submitted", "processing", "polling", "real_task_pending"]);

function shouldPollRun(run: GenerationRun | null) {
  if (!run) {
    return false;
  }
  const runStatus = String(run.status ?? "").toLowerCase();
  const assemblyStatus = String(run.preview.assembly_status ?? "").toLowerCase();
  const seedanceStatus = String(run.preview.video_task_status ?? "").toLowerCase();
  const pendingVideoArtifact = run.artifacts.some(
    (artifact) =>
      ["video_real", "seedance_shot_clip", "seedance_draft_video", "seedance_replacement_clip"].includes(artifact.artifact_type) &&
      activeStatuses.has(String(artifact.status ?? "").toLowerCase()),
  );
  return activeStatuses.has(runStatus) || activeStatuses.has(assemblyStatus) || activeStatuses.has(seedanceStatus) || pendingVideoArtifact;
}

function statusBadgeClass(status: string) {
  const value = status.toLowerCase();
  if (value === "succeeded" || value === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (value === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (activeStatuses.has(value)) {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

export default function AgentPage() {
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [experiments, setExperiments] = useState<ExperimentAnalysis[]>([]);
  const [selectedRun, setSelectedRun] = useState<GenerationRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const totalDuration = useMemo(
    () => selectedRun?.agents.reduce((sum, step) => sum + step.duration_ms, 0) ?? 0,
    [selectedRun],
  );

  useEffect(() => {
    refreshRuns();
  }, []);

  useEffect(() => {
    if (!selectedRun?.run_id || !shouldPollRun(selectedRun)) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const nextRun = await getGenerationRun(selectedRun.run_id);
        if (cancelled) {
          return;
        }
        setSelectedRun(nextRun);
        setRuns((current) => current.map((item) => (item.run_id === nextRun.run_id ? nextRun : item)));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to refresh generation run");
        }
      }
    };
    const interval = window.setInterval(() => {
      void poll();
    }, 2000);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [selectedRun]);

  async function refreshRuns() {
    setLoading(true);
    setError(null);
    try {
      const [data, nextExperiments] = await Promise.all([listGenerationRuns(), listExperiments()]);
      setRuns(data);
      setExperiments(nextExperiments);
      const lastRunId = window.localStorage.getItem("viralcutai:lastRunId");
      const preferred = data.find((run) => run.run_id === lastRunId) ?? data[0] ?? null;
      setSelectedRun(preferred);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load generation runs");
    } finally {
      setLoading(false);
    }
  }

  async function selectRun(runId: string) {
    setError(null);
    try {
      const run = await getGenerationRun(runId);
      setSelectedRun(run);
      window.localStorage.setItem("viralcutai:lastRunId", runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load generation run");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Trace Console"
        title="Inspect the real Studio run"
        description="Studio runs become readable agent traces here. Inputs, outputs, providers, fallbacks, and latency all come from the database."
        badges={["GET /generation-runs", "AgentStep", "provider trace"]}
      />

      <section className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="xl:sticky xl:top-24 xl:self-start">
          <CardHeader>
            <div>
              <CardTitle>Runs</CardTitle>
              <CardDescription>Select a Studio run to inspect its three Agent steps.</CardDescription>
            </div>
            <Button size="icon" variant="outline" onClick={refreshRuns} disabled={loading} aria-label="Refresh runs">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            </Button>
          </CardHeader>
          <div className="space-y-3">
            {runs.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => selectRun(run.run_id)}
                className={`w-full rounded-lg border p-4 text-left transition ${
                  selectedRun?.run_id === run.run_id
                    ? "border-blue-200 bg-blue-50"
                    : "border-black/10 bg-white hover:bg-[#f5f5f7]"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-medium text-slate-950">{run.request_payload.product_name}</p>
                  <Badge className={statusBadgeClass(run.status)}>{run.status}</Badge>
                </div>
                <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{run.summary}</p>
              </button>
            ))}
            {!runs.length && !loading ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm leading-6 text-slate-500">
                No runs yet. Create one in <Link className="text-blue-600" href="/studio">Studio</Link>.
              </div>
            ) : null}
            {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
          </div>
        </Card>

        <div className="grid gap-6">
          <section className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
              <p className="text-xs text-slate-500">Selected run</p>
              <p className="mt-2 truncate font-mono text-sm text-slate-950">{selectedRun?.run_id ?? "-"}</p>
            </div>
            <div className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
              <p className="text-xs text-slate-500">Assets / events</p>
              <p className="mt-2 font-mono text-sm text-slate-950">{selectedRun ? `${selectedRun.assets.length} / ${selectedRun.events.length}` : "0 / 0"}</p>
            </div>
            <div className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
              <p className="text-xs text-slate-500">Trace duration</p>
              <p className="mt-2 font-mono text-sm text-slate-950">{totalDuration}ms</p>
            </div>
          </section>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>LangGraph Node Trace</CardTitle>
                <CardDescription>{selectedRun ? selectedRun.summary : "Select a run to inspect its Agent trace."}</CardDescription>
              </div>
              <GitBranch className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="grid gap-3">
              {selectedRun?.agents.map((step) => (
                <div key={step.id} className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge>0{step.order_index}</Badge>
                      <p className="font-medium text-slate-950">{step.agent_name}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ProviderTruthBadge mode={step.execution_mode} />
                      <Badge className={statusBadgeClass(step.status)}>{step.status}</Badge>
                      <span className="font-mono text-xs text-slate-500">{step.duration_ms}ms</span>
                    </div>
                  </div>
                  <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
                    <div className="min-w-0 rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                      <p className="text-xs text-slate-500">provider</p>
                      <p className="mt-2 break-words text-sm text-slate-800">{step.provider}</p>
                      <p className="mt-3 text-xs text-slate-500">model</p>
                      <p className="mt-2 break-words text-sm text-slate-800">{step.model}</p>
                      <p className="mt-3 text-xs text-slate-500">fallback</p>
                      <p className="mt-2 break-words text-xs leading-5 text-slate-500">{humanizeProviderText(step.fallback)}</p>
                      <p className="mt-3 text-xs text-slate-500">provider truth</p>
                      <p className="mt-2 break-words text-xs font-medium leading-5 text-slate-700">{providerTruthText(step.execution_mode)}</p>
                      <p className="mt-2 break-words text-xs leading-5 text-slate-500">{humanizeProviderText(step.provider_message)}</p>
                    </div>
                    <div className="min-w-0">
                      <p className="mb-2 text-xs text-slate-500">input</p>
                      <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
                        {displayJson(step.input)}
                      </pre>
                    </div>
                    <div className="min-w-0">
                      <p className="mb-2 text-xs text-slate-500">output</p>
                      <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
                        {displayJson(step.output)}
                      </pre>
                    </div>
                  </div>
                  {getSubsteps(step.output).length ? (
                    <details className="mt-4 rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                      <summary className="cursor-pointer text-sm font-medium text-slate-950">
                        Internal substeps ({getSubsteps(step.output).length})
                      </summary>
                      <div className="mt-3 grid gap-3">
                        {getSubsteps(step.output).map((substep) => (
                          <div key={`${step.id}-${substep.substep_name}`} className="rounded-md border border-black/10 bg-white p-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-sm font-medium text-slate-950">{substep.substep_name.replaceAll("_", " ")}</p>
                              <div className="flex flex-wrap items-center gap-2">
                                <ProviderTruthBadge mode={substep.execution_mode} />
                                <Badge>{substep.status}</Badge>
                                <span className="font-mono text-[11px] text-slate-500">{substep.duration_ms}ms</span>
                              </div>
                            </div>
                            <p className="mt-2 break-words text-xs leading-5 text-slate-500">{humanizeProviderText(substep.provider_message)}</p>
                            <div className="mt-3 grid gap-3 md:grid-cols-2">
                              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                                {displayJson(substep.input_summary)}
                              </pre>
                              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                                {displayJson(substep.output_summary)}
                              </pre>
                            </div>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
              ))}
              {!selectedRun ? (
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
                  Studio runs will appear here.
                </div>
              ) : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Run Events</CardTitle>
                <CardDescription>Progress records saved around the same GenerationRun.</CardDescription>
              </div>
              <RefreshCcw className="h-5 w-5 text-cyan-700" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-2">
              {selectedRun?.events.map((event) => (
                <div key={event.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{event.event_type.replaceAll("_", " ")}</p>
                    <Badge>{event.status}</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{event.message}</p>
                </div>
              ))}
              {!selectedRun ? (
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500 md:col-span-2">
                  Run events will appear here.
                </div>
              ) : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Artifacts Written By Agents</CardTitle>
                <CardDescription>These records come from MediaArtifact, not static tables.</CardDescription>
              </div>
              <SearchCode className="h-5 w-5 text-amber-600" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-2">
              {selectedRun?.artifacts.map((artifact) => (
                <div key={artifact.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{displayArtifactTitle(artifact)}</p>
                    <Badge>{humanizeProviderText(artifact.artifact_type.replaceAll("_", " "))}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <ProviderTruthBadge mode={artifactProviderMode(artifact.status, artifact.payload)} />
                    <p className="text-xs text-slate-500">{artifact.provider}</p>
                  </div>
                  {artifact.payload.mock_reason ? (
                    <p className="mt-2 break-words text-xs leading-5 text-amber-700">{humanizeProviderText(artifact.payload.mock_reason)}</p>
                  ) : null}
                  {artifact.payload.failure_reason ? (
                    <p className="mt-2 break-words text-xs leading-5 text-rose-700">{humanizeProviderText(artifact.payload.failure_reason)}</p>
                  ) : null}
                  <pre className="mt-3 max-h-40 max-w-full overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-slate-500">
                    {displayJson(artifact.payload)}
                  </pre>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Experiment Analysis Graph</CardTitle>
                <CardDescription>Attribution Agent traces from A/B analyses.</CardDescription>
              </div>
              <SearchCode className="h-5 w-5 text-cyan-700" />
            </CardHeader>
            <div className="grid gap-3">
              {experiments.slice(0, 3).map((experiment) => (
                <div key={experiment.experiment_id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium text-slate-950">{experiment.title}</p>
                    <Badge>{experiment.result.winner_label ?? "analysis"}</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{experiment.summary}</p>
                  <div className="mt-3 grid gap-3">
                    {experiment.trace.map((step) => (
                      <pre key={`${experiment.experiment_id}-${step.agent_name}`} className="max-h-48 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">
                        {displayJson(step)}
                      </pre>
                    ))}
                  </div>
                </div>
              ))}
              {!experiments.length ? (
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
                  Run an A/B analysis in Analytics to see the Experiment Graph trace.
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      </section>
    </>
  );
}
