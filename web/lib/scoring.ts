export interface ScoringPlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  rank: number;
  tied?: boolean;
  points: number;
  games: number;
  points_per_game: number;
}

export interface ScoringResp {
  league_id: string;
  league_name: string;
  season: number;
  through_week: number;
  updated_at: string;
  players: ScoringPlayer[];
  franchises: ScoringFranchise[];
}

export type ScoringRosterPlayer = Omit<ScoringPlayer, "rank" | "points" | "points_per_game"> & {
  rank: number | null;
  points: number | null;
  points_per_game: number | null;
};

export interface ScoringFranchise {
  roster_id: number;
  owner_id: string | null;
  name: string;
  owner_name: string | null;
  players: ScoringRosterPlayer[];
}
