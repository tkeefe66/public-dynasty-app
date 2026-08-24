Single-select switch — the ONE dialect for year filters, metric switches and view toggles. Never write a bespoke pill group.

```jsx
<SegmentControl
  label="Filter trades by season"
  options={["All-time", "2025", "2024", "2023"]}
  value={year}
  onChange={setYear}
/>
```

An underline run: options as a plain mono run, the active one in full ink with a 2px stamp underline. It is **not** a pill in a well — that drawing cost 50px per control and these arrive in pairs, which put 120px of chrome above the consuming app's production chart. The active segment must still change SHAPE, not just colour; the underline is what satisfies that at 24px.

The run is ~24px tall but every option keeps a **44px tap target** via a transparent absolutely-positioned box. Do not swap that for `minHeight: 44` — that hands the row its height back, which is the whole thing this drawing exists to avoid.

It wraps at narrow widths rather than scrolling sideways, which the app's drift guard bans.

**Place it beside the heading it filters, not at the opposite margin.** A filter changes what a heading names, so it reads as part of the heading; pushed to the far right of a wide viewport it ends up a foot from the words it modifies. Counts, scope lines and actions (a back link, a button) keep the right.
