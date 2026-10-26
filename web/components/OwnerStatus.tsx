import { OwnerRef } from "@/lib/types";
import { ownerStatusText } from "@/lib/owner-membership";

/** One vocabulary for historical names and profiles, independent of view year. */
export function OwnerStatus({ owner }: { owner: OwnerRef }) {
  const label = ownerStatusText(owner);
  if (!label) return null;
  return <span className="block text-label font-normal text-dim leading-snug" title={
    owner.membership_status === "former" ? label : "Latest league roster is incomplete or unavailable. Refresh league data to verify membership."
  }>{label}</span>;
}
