"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, CheckCircle2, Circle, Images, Library, Loader2, Scissors, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  listAssets,
  listExperiments,
  listGenerationRuns,
  listViralFactors,
  listViralVideos,
  type GenerationRun,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export type WorkflowStepId = "assets" | "library" | "studio" | "editor" | "analytics";
export type WorkflowStepStatus = "not_started" | "ready" | "in_progress" | "done" | "needs_attention";

export type WorkflowStep = {
  id: WorkflowStepId;
  href: string;
  label: string;
  shortLabel: string;
  status: WorkflowStepStatus;
  detail: string;
  primaryActionLabel: string;
};

export type WorkflowSnapshot = {
  loading: boolean;
  assetCount: number;
  factorCount: number;
  referenceCount: number;
  experimentCount: number;
  latestRun: GenerationRun | null;
  latestRunId: string | null;
  assembledDone: boolean;
  nextStep: WorkflowStep;
  steps: WorkflowStep[];
};

const stepMeta: Array<{
  id: WorkflowStepId;
  href: string;
  label: string;
  shortLabel: string;
  primaryActionLabel: string;
}> = [
  { id: "assets", href: "/assets", label: "Submit Assets", shortLabel: "Assets", primaryActionLabel: "Upload assets" },
  { id: "library", href: "/viral-library", label: "Select Factors", shortLabel: "Factors", primaryActionLabel: "Select factors" },
  { id: "studio", href: "/studio", label: "Run & Results", shortLabel: "Run", primaryActionLabel: "Run agents" },
  { id: "editor", href: "/editor", label: "Edit Video", shortLabel: "Edit", primaryActionLabel: "Open editor" },
  { id: "analytics", href: "/analytics", label: "Analyze", shortLabel: "Analyze", primaryActionLabel: "Analyze run" },
];

const statusLabel: Record<WorkflowStepStatus, string> = {
  not_started: "Not started",
  ready: "Ready",
  in_progress: "In progress",
  done: "Done",
  needs_attention: "Needs attention",
};

const statusClass: Record<WorkflowStepStatus, string> = {
  not_started: "border-slate-200 bg-white text-slate-500",
  ready: "border-blue-200 bg-blue-50 text-blue-700",
  in_progress: "border-blue-200 bg-blue-50 text-blue-700",
  done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  needs_attention: "border-amber-200 bg-amber-50 text-amber-700",
};

export function useWorkflowState(): WorkflowSnapshot {
  const [assetCount, setAssetCount] = useState(0);
  const [factorCount, setFactorCount] = useState(0);
  const [referenceCount, setReferenceCount] = useState(0);
  const [experimentCount, setExperimentCount] = useState(0);
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.all([listAssets(), listViralVideos(), listViralFactors(), listGenerationRuns(), listExperiments()])
      .then(([assets, videos, factors, nextRuns, experiments]) => {
        if (!active) {
          return;
        }
        setAssetCount(assets.length);
        setReferenceCount(videos.length);
        setFactorCount(factors.length);
        setRuns(nextRuns);
        setExperimentCount(experiments.length);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return useMemo(() => {
    const storedRunId = typeof window !== "undefined" ? window.localStorage.getItem("viralcutai:lastRunId") : null;
    const latestRun = runs.find((run) => run.run_id === storedRunId) ?? runs[0] ?? null;
    const latestRunId = latestRun?.run_id ?? null;
    const librarySignals = referenceCount + factorCount;
    const runStatus = String(latestRun?.status ?? "").toLowerCase();
    const assemblyStatus = String(latestRun?.preview.assembly_status ?? "").toLowerCase();
    const assembledDone = Boolean(
      latestRun &&
        !latestRun.preview.assembled_stale &&
        (latestRun.preview.assembled_video_url ||
          (latestRun.preview.assembled_exports && Object.keys(latestRun.preview.assembled_exports).length > 0) ||
          assemblyStatus === "succeeded"),
    );
    const runDone = runStatus === "succeeded";
    const runActive = ["queued", "running", "pending", "processing"].includes(runStatus);
    const assemblyActive = ["queued", "running", "processing"].includes(assemblyStatus);
    const runFailed = ["failed", "error"].includes(runStatus);
    const assemblyFailed = ["failed", "error"].includes(assemblyStatus);

    const statuses: Record<WorkflowStepId, WorkflowStepStatus> = {
      assets: assetCount > 0 ? "done" : "ready",
      library: librarySignals > 0 ? "done" : assetCount > 0 ? "ready" : "not_started",
      studio: runFailed ? "needs_attention" : runActive ? "in_progress" : runDone ? "done" : assetCount > 0 && librarySignals > 0 ? "ready" : "not_started",
      editor: assemblyFailed ? "needs_attention" : assemblyActive ? "in_progress" : assembledDone ? "done" : runDone ? "ready" : "not_started",
      analytics: experimentCount > 0 ? "done" : assembledDone ? "ready" : "not_started",
    };

    const details: Record<WorkflowStepId, string> = {
      assets: assetCount > 0 ? `${assetCount} assets ready` : "Upload product videos or images",
      library: librarySignals > 0 ? `${referenceCount} refs / ${factorCount} factors` : "Pick viral references and factors",
      studio: latestRun ? `${latestRun.request_payload.product_name} / ${latestRun.status}` : "No generation run yet",
      editor: assembledDone ? `${latestRun?.preview.assembled_duration_seconds ?? "-"}s assembled` : runDone ? "Ready for timeline editing" : "Waiting for a run",
      analytics: experimentCount > 0 ? `${experimentCount} analyses` : assembledDone ? "Ready for metric analysis" : "Waiting for assembled video",
    };

    const steps = stepMeta.map((step) => ({
      ...step,
      status: statuses[step.id],
      detail: details[step.id],
    }));
    const nextStep = steps.find((step) => step.status === "needs_attention") ?? steps.find((step) => step.status === "ready") ?? steps.find((step) => step.status === "in_progress") ?? steps[steps.length - 1];

    return {
      loading,
      assetCount,
      factorCount,
      referenceCount,
      experimentCount,
      latestRun,
      latestRunId,
      assembledDone,
      nextStep,
      steps,
    };
  }, [assetCount, experimentCount, factorCount, loading, referenceCount, runs]);
}

export function WorkflowStepper({ currentStep }: { currentStep?: WorkflowStepId }) {
  const pathname = usePathname();
  const snapshot = useWorkflowState();
  const activeStep = currentStep ?? stepForPath(pathname);

  return (
    <div className="border-t border-black/5 bg-[#f5f5f7]">
      <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-4 py-3 sm:px-6 lg:overflow-x-visible lg:px-8">
        {snapshot.steps.map((step, index) => {
          const active = step.id === activeStep;
          return (
            <Link
              key={step.id}
              href={step.href}
              className={cn(
                "group flex min-w-[150px] flex-1 items-center gap-3 rounded-md border px-3 py-2 transition xl:min-w-0",
                active ? "border-blue-200 bg-white shadow-sm shadow-black/[0.04]" : "border-transparent bg-transparent hover:bg-white/70",
              )}
            >
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border",
                  active ? "border-blue-200 bg-blue-50 text-blue-700" : "border-black/10 bg-white text-slate-500",
                )}
              >
                <WorkflowStepIcon step={step.id} className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-xs font-medium text-slate-950">
                    {index + 1}. {step.label}
                  </p>
                  <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]", statusClass[step.status])}>
                    <WorkflowStatusIcon status={step.status} className="h-3 w-3" />
                    {statusLabel[step.status]}
                  </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-slate-500">{step.detail}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export function stepForPath(pathname: string): WorkflowStepId | undefined {
  if (pathname.startsWith("/assets")) {
    return "assets";
  }
  if (pathname.startsWith("/viral-library")) {
    return "library";
  }
  if (pathname.startsWith("/studio")) {
    return "studio";
  }
  if (pathname.startsWith("/editor")) {
    return "editor";
  }
  if (pathname.startsWith("/analytics")) {
    return "analytics";
  }
  return undefined;
}

function WorkflowStepIcon({ step, className }: { step: WorkflowStepId; className?: string }) {
  if (step === "assets") {
    return <Images className={className} />;
  }
  if (step === "library") {
    return <Library className={className} />;
  }
  if (step === "studio") {
    return <Sparkles className={className} />;
  }
  if (step === "editor") {
    return <Scissors className={className} />;
  }
  return <BarChart3 className={className} />;
}

function WorkflowStatusIcon({ status, className }: { status: WorkflowStepStatus; className?: string }) {
  if (status === "done") {
    return <CheckCircle2 className={className} />;
  }
  if (status === "in_progress") {
    return <Loader2 className={cn(className, "animate-spin")} />;
  }
  if (status === "needs_attention") {
    return <TriangleAlert className={className} />;
  }
  return <Circle className={className} />;
}
