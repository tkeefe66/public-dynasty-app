export interface ScoringPlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  rank: number;
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
}
