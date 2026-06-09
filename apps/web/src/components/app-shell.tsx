"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, FileVideo, Images, LayoutDashboard, Library, Network, Scissors, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { WorkflowStepper } from "@/components/workflow-stepper";
import { API_BASE, getHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/assets", label: "My Assets", icon: Images },
  { href: "/viral-library", label: "Viral Library", icon: Library },
  { href: "/studio", label: "Studio", icon: Sparkles },
  { href: "/editor", label: "Editor", icon: Scissors },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/agent", label: "Trace", icon: Network },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [apiStatus, setApiStatus] = useState("checking");
  const [graphMode, setGraphMode] = useState("LangGraph");
  const [providerSummary, setProviderSummary] = useState("Providers checking");

  useEffect(() => {
    getHealth()
      .then((payload) => {
        setApiStatus(payload.status === "ok" ? "online" : "degraded");
        setGraphMode(payload.graph);
        const configured = Object.values(payload.providers ?? {}).filter((status) => status === "configured").length;
        const total = Object.keys(payload.providers ?? {}).length;
        setProviderSummary(`${configured}/${total} providers configured`);
      })
      .catch(() => setApiStatus("offline"));
  }, []);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-black/10 bg-white/85 px-4 py-5 backdrop-blur-xl lg:block">
        <Link href="/studio" className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-slate-950 text-white shadow-sm shadow-black/20">
            <FileVideo className="h-5 w-5" />
          </div>
          <div>
            <p className="text-base font-semibold text-slate-950">ViralCutAI</p>
            <p className="text-xs text-slate-500">Agent workspace</p>
          </div>
        </Link>

        <nav className="mt-8 space-y-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex h-10 items-center gap-3 rounded-md px-3 text-sm text-slate-500 transition",
                  active ? "bg-white text-slate-950 shadow-sm shadow-black/[0.06]" : "hover:bg-white/70 hover:text-slate-950",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="absolute inset-x-4 bottom-5 rounded-md border border-black/10 bg-white/80 p-4 shadow-sm shadow-black/[0.03]">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-blue-600" />
          <p className="text-sm font-medium text-slate-950">Single main chain</p>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">
            My Assets stay private. Viral Library stores external playbook analysis only.
        </p>
          <Badge className="mt-3 border-blue-200 bg-blue-50 text-blue-700">/generation-runs</Badge>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b border-black/10 bg-white/80 px-4 py-3 backdrop-blur-xl sm:px-6 lg:px-8">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2 overflow-x-auto lg:hidden">
              {navigation.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "whitespace-nowrap rounded-md px-3 py-2 text-xs text-slate-500",
                    pathname === item.href && "bg-white text-slate-950 shadow-sm shadow-black/[0.06]",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </div>
            <div className="hidden min-w-0 text-sm font-medium text-slate-700 lg:block">
              {graphMode} / {providerSummary}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="hidden font-mono text-xs text-slate-400 md:inline">{API_BASE}</span>
              <Badge
                className={cn(
                  apiStatus === "online"
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-rose-200 bg-rose-50 text-rose-700",
                )}
              >
                API {apiStatus}
              </Badge>
            </div>
          </div>
        </header>
        <WorkflowStepper />
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</div>
      </div>
    </div>
  );
}
