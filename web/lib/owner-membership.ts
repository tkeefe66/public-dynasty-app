import { OwnerRef } from "./types";

export type OwnerPopulation = "current" | "all";

export function ownerStatusText(owner: OwnerRef): string | null {
  // A web-first rollout may receive the old response shape. Do not invent a
  // status; the new API explicitly returns unverified when evidence is missing.
  if (!owner.membership_status || owner.membership_status === "current") return null;
  return owner.membership_status === "former"
    ? `Former owner${owner.last_active_season ? ` · last played ${owner.last_active_season}` : ""}`
    : "Membership unverified";
}

/** Plain-text owner selectors and draft tables use the same status vocabulary. */
export function ownerNameWithStatus(owner?: OwnerRef | null, fallbackId?: string): string {
  if (!owner) return fallbackId ?? "Unknown";
  const status = ownerStatusText(owner);
  return `${owner.owner_name}${status ? ` · ${status}` : ""}`;
}

/** Preserve historical seasons. Unknown membership stays visible and labelled. */
export function membershipRows<T extends { owner: OwnerRef }>(
  rows: T[], population: OwnerPopulation, historical: boolean,
): T[] {
  return historical || population === "all" ? rows
    : rows.filter((row) => row.owner.membership_status !== "former");
}
