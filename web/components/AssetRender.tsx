interface Asset {
  kind?: string;
  name?: string;
  player_id?: string;
  season?: number;
  round?: number;
  via_pick?: { season: number; round: number; original_owner_user_id?: string };
  original_owner_user_id?: string;
  drafted_player_id?: string;
  drafted_player_name?: string;
  amount?: number;
}

interface Props {
  asset: Asset;
  displayNames: Record<string, string>;
  /** user_id of the side giving this asset — used to suppress redundant "(orig:)" */
  giverUserId?: string;
}

function ordinal(n: number): string {
  if (n % 100 >= 11 && n % 100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" }[n % 10 as 1 | 2 | 3]) ?? "th"}`;
}

export function AssetRender({ asset, displayNames, giverUserId }: Props) {
  if (asset.name && asset.via_pick) {
    const origUid = asset.via_pick.original_owner_user_id ?? "";
    const orig = displayNames[origUid] ?? (origUid || "?");
    const showOrig = origUid && origUid !== giverUserId;
    return (
      <span>
        {asset.via_pick.season} {ordinal(asset.via_pick.round)} pick
        {showOrig && <span className="hidden sm:inline"> (orig: {orig})</span>}{" "}
        <span className="text-dim">→</span> <span className="font-medium">{asset.name}</span>
      </span>
    );
  }
  if (asset.name && !asset.season && !asset.round) {
    return <span className="font-medium">{asset.name}</span>;
  }
  if (asset.season !== undefined && asset.round !== undefined) {
    // A bare pick on this trade leg. If `drafted_player_name` is set, the pick
    // was eventually drafted into that player but this owner did NOT keep him
    // (they flipped the pick onward) — so we annotate what it became without
    // implying ownership, distinct from the via_pick "→ player" above which
    // means the owner actually drafted and kept the player. Otherwise it's an
    // undrafted future pick; omit the "(orig: …)" suffix since the original
    // owner often resolves to a noisy raw Sleeper ID.
    return (
      <span>
        {asset.season} {ordinal(asset.round)} pick
        {asset.drafted_player_name && (
          <span className="text-dim"> · became {asset.drafted_player_name}</span>
        )}
      </span>
    );
  }
  if (asset.amount !== undefined) {
    return <span>${asset.amount} FAAB</span>;
  }
  return <span>?</span>;
}
