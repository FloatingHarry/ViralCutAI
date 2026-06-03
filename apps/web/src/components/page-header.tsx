import { Badge } from "@/components/ui/badge";

export function PageHeader({
  eyebrow,
  title,
  description,
  badges = [],
}: {
  eyebrow: string;
  title: string;
  description: string;
  badges?: string[];
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 border-b border-black/10 pb-5 md:flex-row md:items-end md:justify-between">
      <div>
        <p className="text-sm font-medium text-blue-600">{eyebrow}</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-950 md:text-3xl">{title}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{description}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {badges.map((badge) => (
          <Badge key={badge}>{badge}</Badge>
        ))}
      </div>
    </div>
  );
}
