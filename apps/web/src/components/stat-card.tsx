import { Card } from "@/components/ui/card";

export function StatCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-2 font-mono text-2xl text-slate-950">{value}</p>
      <p className="mt-2 text-sm leading-5 text-slate-500">{detail}</p>
    </Card>
  );
}
