import Link from "next/link";
import { OwnerRef, Year } from "@/lib/types";

/** Season eligibility is separate from whether an owner is still in the league. */
export function SeasonMembershipNotice({ leagueId, year, owners = [] }: {
  leagueId: string; year: Year; owners?: OwnerRef[];
}) {
  if (year === "all" || owners.length === 0) return null;
  return <section aria-label={`${year} participation unverified`} className="my-4 border border-rule rounded-panel p-4">
    <h2 className="text-figure font-bold">{year} participation unverified</h2>
    <p className="text-figure text-dim mt-1">
      Not included in {year} rankings. We don’t have enough season evidence to confirm these owners participated.
      Refresh league data to check again. Their history is still available.
    </p>
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-figure">
      {owners.map((owner) => <li key={owner.user_id}>
        <Link className="underline underline-offset-2" href={`/league/${leagueId}/owner/${owner.user_id}`}>
          {owner.owner_name}
        </Link>
      </li>)}
    </ul>
  </section>;
}
