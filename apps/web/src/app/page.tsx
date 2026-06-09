"use client";

import Link from "next/link";
import { ArrowRight, BarChart3, CheckCircle2, Clock3, Images, Library, Scissors, Sparkles, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWorkflowState, type WorkflowStep, type WorkflowStepId, type WorkflowStepStatus } from "@/components/workflow-stepper";
import { cn } from "@/lib/utils";

const statusText: Record<WorkflowStepStatus, string> = {
  not_started: "Not started",
  ready: "Ready",
  in_progress: "In progress",
  done: "Done",
  needs_attention: "Needs attention",
};

export default function HomePage() {
  const workflow = useWorkflowState();
  const latest = workflow.latestRun;

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 sm:p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="rounded-lg border border-black/10 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <Badge className="border-blue-200 bg-blue-50 text-blue-700">Workflow Cockpit</Badge>
                <h1 className="mt-4 text-2xl font-semibold text-slate-950 md:text-3xl">Build one commerce video through five clear steps.</h1>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-500">
                  Submit private assets, select viral factors, run the agent chain, edit the timeline, then analyze real results.
                </p>
              </div>
              <Link href={workflow.nextStep.href}>
                <Button variant="secondary">
                  {workflow.nextStep.primaryActionLabel}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              {workflow.steps.map((step) => (
                <StepPanel key={step.id} step={step} />
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-black/10 bg-white p-5">
            <p className="text-sm font-medium text-slate-950">Current project</p>
            <p className="mt-1 text-xs text-slate-500">{latest ? latest.request_payload.product_name : "No run yet"}</p>
            <div className="mt-4 grid gap-3">
              <Metric label="Assets" value={String(workflow.assetCount)} />
              <Metric label="References" value={String(workflow.referenceCount)} />
              <Metric label="Factors" value={String(workflow.factorCount)} />
              <Metric label="Analyses" value={String(workflow.experimentCount)} />
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Latest run</CardTitle>
              <CardDescription>{latest ? latest.summary : "Create a Studio run after assets and factors are ready."}</CardDescription>
            </div>
            <Badge className={latest?.status === "succeeded" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : ""}>
              {latest?.status ?? "empty"}
            </Badge>
          </CardHeader>
          <div className="grid gap-3 md:grid-cols-3">
            <RunSignal label="Agent run" value={latest?.status ?? "Not started"} status={latest?.status === "succeeded" ? "done" : latest ? "in_progress" : "not_started"} />
            <RunSignal
              label="Editor export"
              value={workflow.assembledDone ? `${latest?.preview.assembled_duration_seconds ?? "-"}s ready` : "No assembled video"}
              status={workflow.assembledDone ? "done" : latest?.status === "succeeded" ? "ready" : "not_started"}
            />
            <RunSignal
              label="Next step"
              value={workflow.nextStep.label}
              status={workflow.nextStep.status}
            />
          </div>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Next action</CardTitle>
              <CardDescription>{workflow.nextStep.detail}</CardDescription>
            </div>
            <IconForStep step={workflow.nextStep.id} />
          </CardHeader>
          <Link href={workflow.nextStep.href}>
            <Button className="w-full" variant="secondary">
              {workflow.nextStep.primaryActionLabel}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            The workflow uses the latest selected run from local storage, then falls back to the newest generation run.
          </p>
        </Card>
      </section>
    </div>
  );
}

function StepPanel({ step }: { step: WorkflowStep }) {
  return (
    <Link href={step.href} className="group">
      <div className="h-full rounded-md border border-black/10 bg-[#f5f5f7] p-3 transition group-hover:border-blue-200 group-hover:bg-blue-50/50">
        <div className="flex items-center justify-between gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-white text-slate-700">
            <StepIcon step={step.id} className="h-4 w-4" />
          </div>
          <StatusBadge status={step.status} />
        </div>
        <p className="mt-3 text-sm font-medium text-slate-950">{step.label}</p>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{step.detail}</p>
      </div>
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-black/10 bg-[#f5f5f7] p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-xl text-slate-950">{value}</p>
    </div>
  );
}

function RunSignal({ label, value, status }: { label: string; value: string; status: WorkflowStepStatus }) {
  return (
    <div className="rounded-md border border-black/10 bg-[#f5f5f7] p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-slate-500">{label}</p>
        <StatusBadge status={status} />
      </div>
      <p className="mt-3 truncate text-sm font-medium text-slate-950">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: WorkflowStepStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]",
        status === "done" && "border-emerald-200 bg-emerald-50 text-emerald-700",
        status === "ready" && "border-blue-200 bg-blue-50 text-blue-700",
        status === "in_progress" && "border-blue-200 bg-blue-50 text-blue-700",
        status === "needs_attention" && "border-amber-200 bg-amber-50 text-amber-700",
        status === "not_started" && "border-slate-200 bg-white text-slate-500",
      )}
    >
      {status === "done" ? <CheckCircle2 className="h-3 w-3" /> : status === "needs_attention" ? <TriangleAlert className="h-3 w-3" /> : <Clock3 className="h-3 w-3" />}
      {statusText[status]}
    </span>
  );
}

function StepIcon({ step, className }: { step: WorkflowStepId; className?: string }) {
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

function IconForStep({ step }: { step: WorkflowStepId }) {
  return <StepIcon step={step} className="h-5 w-5 text-blue-700" />;
}
