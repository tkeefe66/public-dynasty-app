/**
 * The nineteen marks — Furniture. Same names as Agate's `ICON_PATHS`
 * (`web/components/agate/Icon.tsx`) so a call site swaps sets without
 * renaming, but STROKED (1.6, round caps and joins) rather than cut. Agate's
 * set was right angles and 45° edges only "because the system has no
 * radius, so a rounded corner would be the only curve on screen"; Furniture
 * has a 16px radius everywhere, so cut marks fight it.
 *
 * Path data copied verbatim from `.design/components/controls/fx-icon-paths.js`
 * — do not redraw, re-eyeball, or "improve" any of them here.
 *
 * There is no icon library. The app's drift guard bans Lucide by name
 * precisely so this set stays first-party — adding a mark means drawing it
 * on the 16px grid here, not installing a dependency.
 */

export const FX_ICON_PATHS = {
  /* disclosure + sorting */
  "sort-desc": "M4 6.5 L8 10.5 L12 6.5",
  "sort-asc": "M4 9.5 L8 5.5 L12 9.5",
  open: "M4 6.5 L8 10.5 L12 6.5",
  closed: "M6.5 4 L10.5 8 L6.5 12",

  /* direction */
  forward: "M2.8 8 H13.2 M9.6 4.4 L13.2 8 L9.6 11.6",
  back: "M13.2 8 H2.8 M6.4 4.4 L2.8 8 L6.4 11.6",

  /* status */
  info: "M8 2.8 A5.2 5.2 0 1 1 7.99 2.8 Z M8 7.4 V11.2 M8 5.1 H8.01",
  alert: "M8 2.6 L14 12.4 H2 Z M8 6.4 V9.2 M8 10.8 H8.01",
  done: "M3 8.4 L6.3 11.7 L13 5",
  close: "M3.6 3.6 L12.4 12.4 M12.4 3.6 L3.6 12.4",
  add: "M8 3 V13 M3 8 H13",

  /* theme */
  light: "M8 5.4 A2.6 2.6 0 1 1 7.99 5.4 Z M8 1.6 V2.9 M8 13.1 V14.4 M1.6 8 H2.9 M13.1 8 H14.4 M3.5 3.5 L4.4 4.4 M11.6 11.6 L12.5 12.5 M12.5 3.5 L11.6 4.4 M4.4 11.6 L3.5 12.5",
  dark: "M12.2 10.4 A4.6 4.6 0 0 1 5.6 3.8 A5.4 5.4 0 1 0 12.2 10.4 Z",

  /* content */
  copy: "M6 6 H13 A1 1 0 0 1 14 7 V13 A1 1 0 0 1 13 14 H6 A1 1 0 0 1 5 13 V7 A1 1 0 0 1 6 6 Z M3.4 10.6 A1 1 0 0 1 2.4 9.6 V3.4 A1 1 0 0 1 3.4 2.4 H9.6 A1 1 0 0 1 10.6 3.4",
  share: "M10 3.4 H12.6 A1 1 0 0 1 13.6 4.4 V7 M13.6 3.4 L8.6 8.4 M6.6 3.4 H3.4 A1 1 0 0 0 2.4 4.4 V12.6 A1 1 0 0 0 3.4 13.6 H11.6 A1 1 0 0 0 12.6 12.6 V9.6",
  swap: "M2.6 5.6 H12.4 M9.8 3 L12.4 5.6 L9.8 8.2 M13.4 10.4 H3.6 M6.2 7.8 L3.6 10.4 L6.2 13",
  table: "M3.4 2.6 H12.6 A1 1 0 0 1 13.6 3.6 V12.4 A1 1 0 0 1 12.6 13.4 H3.4 A1 1 0 0 1 2.4 12.4 V3.6 A1 1 0 0 1 3.4 2.6 Z M2.4 6.4 H13.6 M2.4 9.8 H13.6",
  season: "M5.2 1.6 V4 M10.8 1.6 V4 M3.4 3 H12.6 A1 1 0 0 1 13.6 4 V12.6 A1 1 0 0 1 12.6 13.6 H3.4 A1 1 0 0 1 2.4 12.6 V4 A1 1 0 0 1 3.4 3 Z M2.4 6.6 H13.6",
  menu: "M2.6 4.4 H13.4 M2.6 8 H13.4 M2.6 11.6 H13.4",
} as const;

/** One of the nineteen mark names. A typo here is a compile error, not a blank icon. */
export type MarkName = keyof typeof FX_ICON_PATHS;

export const FX_ICON_NAMES = Object.keys(FX_ICON_PATHS) as MarkName[];
