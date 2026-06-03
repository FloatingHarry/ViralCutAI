"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BarChart3, CheckCircle2, Images, Library, Network, Play, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { humanizeProviderText } from "@/components/provider-truth";
import { listGenerationRuns, type GenerationRun } from "@/lib/api";

const modules = [
  {
    href: "/studio",
    title: "Agent Studio",
    detail: "Enter a product goal and run the full three-agent chain with one request.",
    icon: Sparkles,
  },
  {
    href: "/assets",
    title: "My Assets",
    detail: "Keep private product images, videos, tags, slices, and retrieval evidence in your workspace.",
    icon: Images,
  },
  {
    href: "/viral-library",
    title: "Viral Library",
    detail: "Analyze external reference URLs into reusable viral factors and templates.",
    icon: Library,
  },
  {
    href: "/agent",
    title: "Trace Console",
    detail: "Inspect each agent input, output, provider, fallback, and latency.",
    icon: Network,
  },
  {
    href: "/analytics",
    title: "Run Analytics",
    detail: "Summarize hooks, factors, prompts, artifacts, and compliance from real runs.",
    icon: BarChart3,
  },
];

export default function HomePage() {
  const [runs, setRuns] = useState<GenerationRun[]>([]);

  useEffect(() => {
    listGenerationRuns()
      .then(setRuns)
      .catch(() => undefined);
  }, []);

  const latest = runs[0];
  const artifactCount = useMemo(() => runs.reduce((sum, run) => sum + run.artifacts.length, 0), [runs]);
  const assetCount = useMemo(() => runs.reduce((sum, run) => sum + run.assets.length, 0), [runs]);

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-lg border border-black/10 bg-white shadow-sm shadow-black/[0.04]">
        <div className="grid min-h-[420px] gap-0 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="flex flex-col justify-between p-6 sm:p-8">
            <div>
              <Badge className="border-blue-200 bg-blue-50 text-blue-700">LangGraph Agent-only</Badge>
              <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-tight text-slate-950 md:text-6xl">
                Commerce video generation starts with one Agent run.
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-slate-500">
                ViralCutAI keeps private product assets separate from the external viral playbook. Three LangGraph agents combine both inputs into strategy, storyboard, media artifacts, and delivery metadata.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link href="/studio">
                  <Button variant="secondary">
                    <Play className="h-4 w-4" />
                    Start Studio
                  </Button>
                </Link>
                <Link href="/agent">
                  <Button variant="outline">
                    View Trace
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>
            <div className="mt-10 grid gap-3 sm:grid-cols-3">
              <Metric label="Runs" value={String(runs.length)} />
              <Metric label="Run Assets" value={String(assetCount)} />
              <Metric label="Artifacts" value={String(artifactCount)} />
            </div>
          </div>

          <div className="border-t border-black/10 bg-[#f5f5f7] p-6 lg:border-l lg:border-t-0">
            <div className="rounded-lg border border-black/10 bg-white/85 p-4 shadow-sm shadow-black/[0.04]">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-950">Latest run</p>
                  <p className="mt-1 text-xs text-slate-500">{latest ? latest.request_payload.product_name : "No run yet"}</p>
                </div>
                <Badge className={latest?.status === "succeeded" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : ""}>
                  {latest?.status ?? "empty"}
                </Badge>
              </div>
              <div className="mt-5 aspect-[9/16] rounded-lg border border-black/10 bg-slate-950 p-5 text-white shadow-inner">
                <div className="flex h-full flex-col justify-between">
                  <div>
                    <p className="text-xs text-white/50">Latest video artifact</p>
                    <p className="mt-3 text-lg font-medium leading-7">
                      {latest?.preview.video_url
                        ? "Real Seedance video is available in Studio."
                        : humanizeProviderText(latest?.artifacts.find((artifact) => artifact.artifact_type.includes("video"))?.payload.description) ||
                          "Run Studio to generate a provider-tracked video artifact."}
                    </p>
                  </div>
                  <div className="grid gap-2">
                    {(latest?.agents ?? ["Viral Strategy Agent", "Script & Storyboard Agent", "Render & Review Agent"]).map((item) => {
                      const label = typeof item === "string" ? item : item.agent_name;
                      return (
                        <div key={label} className="flex items-center gap-2 rounded-md bg-white/10 px-3 py-2 text-xs text-white/80">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                          {label}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        {modules.map((item) => {
          const Icon = item.icon;
          return (
            <Link key={item.href} href={item.href} className="group">
              <Card className="h-full transition group-hover:-translate-y-0.5 group-hover:shadow-md group-hover:shadow-black/[0.06]">
                <CardHeader>
                  <div>
                    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-slate-950 text-white">
                      <Icon className="h-5 w-5" />
                    </div>
                    <CardTitle>{item.title}</CardTitle>
                    <CardDescription>{item.detail}</CardDescription>
                  </div>
                  <ArrowRight className="h-5 w-5 text-slate-300 transition group-hover:text-blue-600" />
                </CardHeader>
              </Card>
            </Link>
          );
        })}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-2 font-mono text-2xl text-slate-950">{value}</p>
    </div>
  );
}
