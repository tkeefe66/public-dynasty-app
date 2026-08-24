export type SignalRow = {
  key: string; label: string; weight: number; raw: string; contribution: number;
};
export type PillarRow = {
  key: "results" | "assets";
  label: string; weight: number; contribution: number; signals: SignalRow[];
};

// v2: 0.60 Results + 0.40 Assets, no Skill pillar (src/sleeper_dynasty/engine
// /gm_rating.py::V2_PILLAR_WEIGHTS["v2_dynasty"], V2_SIGNAL_WEIGHTS). Signal
// contributions are hand-picked to sum exactly (not just within rounding) so
// the worked example never needs a rounding-slop caveat.
export const SAMPLE = {
  name: "Marcus",
  letter: "B",
  rating: 1674,
  pillars: [
    {
      key: "results", label: "Results", weight: 0.60, contribution: 132,
      signals: [
        { key: "expected_wins", label: "Expected Wins", weight: 0.55, raw: "58% all-play win rate", contribution: 73 },
        { key: "playoff_success", label: "Playoff Success", weight: 0.30, raw: "1.4, recency-weighted", contribution: 40 },
        { key: "luck", label: "Luck", weight: 0.15, raw: "+4% vs. expected", contribution: 19 },
      ],
    },
    {
      key: "assets", label: "Assets", weight: 0.40, contribution: 42,
      signals: [
        { key: "roster_value_share", label: "Roster Value Share", weight: 0.45, raw: "9.6% of league value", contribution: 22 },
        { key: "young_core_share", label: "Young Core Share", weight: 0.35, raw: "62% of value in players 25 or younger", contribution: 14 },
        { key: "draft_capital", label: "Draft Capital", weight: 0.20, raw: "above-average holdings", contribution: 6 },
      ],
    },
  ] as PillarRow[],
};

export const SECTIONS: { id: string; title: string }[] = [
  { id: "verdict", title: "The verdict" },
  { id: "pillars", title: "The two pillars" },
  { id: "signals", title: "Inside each pillar" },
  { id: "metrics", title: "The trade metrics" },
  { id: "math", title: "The math" },
  { id: "columns", title: "Supporting columns" },
  { id: "words", title: "How the words are written" },
  { id: "sources", title: "Sources & limits" },
];
