import type { RatingScope } from "@/lib/types";

export function RatingScopeNotice({ scope }: { scope?: RatingScope | null }) {
  if (!scope) return null;
  return (
    <p className="mb-4 text-sm text-dim" role="status">
      <span className="font-medium text-ink">{scope.label}</span>
      {scope.as_of && scope.status === "ready" && <> · As of {scope.as_of.slice(0, 10)}</>}
      {scope.reason && <>. {scope.reason}</>}
    </p>
  );
}
