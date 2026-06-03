import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function ProviderTruthBadge({ mode }: { mode?: string | null }) {
  const normalized = mode ?? "mock_missing_config";
  const label =
    normalized === "real"
      ? "Real output"
      : normalized === "local"
        ? "Local assembled output"
      : normalized === "real_failed"
        ? "Provider failed"
        : normalized === "mock_missing_config"
          ? "Not connected"
          : normalized;
  return (
    <Badge
      className={cn(
        normalized === "real" && "border-emerald-200 bg-emerald-50 text-emerald-700",
        normalized === "local" && "border-blue-200 bg-blue-50 text-blue-700",
        normalized === "real_failed" && "border-rose-200 bg-rose-50 text-rose-700",
        normalized === "mock_missing_config" && "border-slate-200 bg-slate-50 text-slate-600",
      )}
    >
      {label}
    </Badge>
  );
}

export function providerTruthText(mode?: string | null) {
  if (mode === "real") {
    return "Real provider output";
  }
  if (mode === "real_failed") {
    return "Provider failed";
  }
  if (mode === "local") {
    return "Local assembled output";
  }
  if (mode === "mock_missing_config") {
    return "Provider not connected";
  }
  return mode ?? "Provider status pending";
}

export function humanizeProviderText(value?: unknown) {
  return String(value ?? "")
    .replaceAll("mock_missing_config", "not connected")
    .replaceAll("real_failed_mock_used", "provider failed")
    .replace(/missing-config mocks/gi, "not-connected outputs")
    .replace(/missing config mock/gi, "not connected")
    .replace(/mock placeholders/gi, "placeholders")
    .replace(/mock artifacts/gi, "planning artifacts")
    .replace(/mock fallback/gi, "placeholder fallback")
    .replace(/\bmock\b/gi, "placeholder");
}

export function artifactProviderMode(status?: string | null, payload?: Record<string, unknown> | null) {
  if (status === "local_generated") {
    return "local";
  }
  if (status === "real_failed" || status === "provider_failed") {
    return "real_failed";
  }
  if (status === "mock_missing_config") {
    return "mock_missing_config";
  }
  if (payload?.is_real_output === true) {
    return "real";
  }
  if (payload?.failure_reason) {
    return "real_failed";
  }
  if (payload?.mock_reason) {
    return "mock_missing_config";
  }
  return "real";
}
