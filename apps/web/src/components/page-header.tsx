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
    <div className="mb-4 flex flex-col gap-3 border-b border-black/10 pb-3 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-blue-600">{eyebrow}</p>
          {badges.slice(0, 2).map((badge) => (
            <Badge key={badge}>{badge}</Badge>
          ))}
        </div>
        <h1 className="mt-1 text-xl font-semibold text-slate-950 md:text-2xl">{title}</h1>
        <p className="mt-1 max-w-4xl truncate text-xs leading-5 text-slate-500 md:text-sm">{description}</p>
      </div>
      {badges.length > 2 ? (
        <div className="hidden flex-wrap gap-2 xl:flex">
          {badges.slice(2).map((badge) => (
          <Badge key={badge}>{badge}</Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}
