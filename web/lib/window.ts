/** The five competitive-window stages `engine/gm_rating.py::rating_to_stage`
 *  can return, in the fixed order the ladder draws them — low to high.
 *
 *  This is a VALUE CHANGE, not a carry-over: the previous list was the retired
 *  classify_window's five (Rebuilding · Descending · Peaking · Ascending ·
 *  Competing now), which no producer can emit any more. These five match
 *  `.design/components/data/WindowCell.jsx` exactly. */
export const WINDOW_STAGES = [
  "Rebuilding", "Retooling", "Competing", "Contending", "Dynasty",
] as const;

export type WindowStage = (typeof WINDOW_STAGES)[number];
