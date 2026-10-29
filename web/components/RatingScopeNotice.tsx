import type { RatingScope } from "@/lib/types";

export function RatingScopeNotice({ scope }: { scope?: RatingScope | null }) {
  if (!scope || scope.status === "provisional") return null;
  const hasRating = scope.status === "ready";
  return (
    <div className="mb-4 text-sm text-dim" role="status">
      <span className="font-medium text-ink">
        {scope.label}
      </span>
      {scope.as_of && hasRating && <> · As of {scope.as_of.slice(0, 10)}</>}
      {scope.reason && <>. {scope.reason}</>}
      {hasRating && scope.current_valuation_note && <p className="mt-1">{scope.current_valuation_note}</p>}
      {!!scope.excluded_rosters?.length && <>
        <p className="mt-1">Owner coverage: {scope.verified_owner_count} verified owners. Ratings exclude unassigned teams.</p>
        <ul className="list-disc pl-5">
          {scope.excluded_rosters.map(({ roster_id, reason }) => <li key={roster_id}>Team {roster_id}: {reason}</li>)}
        </ul>
      </>}
      {scope.valuation_source && hasRating && <>
        {" · Historical values: "}
        <a href={scope.valuation_source === "dynasty_process" ? "https://dynastyprocess.com" : "https://statsguyfantasy.com"}
          className="underline" target="_blank" rel="noreferrer">
          {scope.valuation_source === "dynasty_process" ? "DynastyProcess" : "Stats Guy Fantasy"}
        </a>
        {scope.prices_as_of && <> ({scope.prices_as_of})</>}
        {scope.valuation_note && <span className="mt-1 block">{scope.valuation_note}</span>}
      </>}
    </div>
  );
}
