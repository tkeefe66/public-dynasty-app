import type { RatingScope } from "@/lib/types";

export function RatingScopeNotice({ scope }: { scope?: RatingScope | null }) {
  if (!scope) return null;
  return (
    <p className="mb-4 text-sm text-dim" role="status">
      <span className="font-medium text-ink">{scope.label}</span>
      {scope.as_of && scope.status === "ready" && <> · As of {scope.as_of.slice(0, 10)}</>}
      {scope.reason && <>. {scope.reason}</>}
      {scope.valuation_source === "stats_guy" && scope.status === "ready" && <>
        {" · Historical values: "}
        <a href="https://statsguyfantasy.com" className="underline" target="_blank" rel="noreferrer">Stats Guy Fantasy</a>
        {scope.prices_as_of && <> ({scope.prices_as_of})</>}
        {scope.valuation_note && <span className="mt-1 block">{scope.valuation_note}</span>}
      </>}
    </p>
  );
}
