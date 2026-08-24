A two-tier ledger head — spanning caps over a normal `Row variant="head"`. Reach for it when a table is wide enough that its labels read as one run of abbreviations with nothing signalling which belong together.

```jsx
<GroupedHead
  cols="66px 84px minmax(140px,420px) 60px 72px 66px 72px 74px 56px 60px"
  groups={[
    { span: 3 },                        // identity: pick · owner · player — capless
    { span: 2, label: "Baseline" },     // ECR · Slot +/-
    { span: 1 },                        // Verdict — one column groups nothing
    { span: 3, label: "Production" },   // Total · Start % · GS
    { span: 1 },                        // Now — capless
  ]}
>
  <SortButton sort="none">Pick</SortButton>
  {/* …one child per column, exactly as Row variant="head" takes them */}
</GroupedHead>
<Row cols="66px 84px minmax(140px,420px) 60px 72px 66px 72px 74px 56px 60px">…</Row>
```

68px total: 6px top padding + an 18px naming tier + the label tier's **44px, which is not negotiable** — that is a SortButton's tap target, and it is the whole reason this is a separate shape instead of a `Row` variant.

Five rules, each of which has a way of going quietly wrong:

- **Eight or more columns.** A seven-column `GroupedHead` is a misuse: the head is not crowded and the tier costs 24px above the data for nothing.
- **Spans sum to the track count.** A capless `{ span: 3 }` for an ungrouped run, never an omitted group — a short sum slides every later cap one column left, which looks like a styling bug and is an arithmetic one.
- **A cap spans two or more columns.** A `label` on a `{ span: 1 }` group names a column that already carries its own name, 24px higher — it groups nothing. Singletons take a capless `{ span: 1 }`.
- **A cap factors out a shared word or a real structural family.** *Points* over Total/Regular/Playoff/Toilet earns it on the shared word; *Production* over Total/Start %/GS earns it on the family, because a percentage and a game count are not points. *Details* over four unrelated columns is decoration. **Re-check a cap whenever its columns change** — this example carried "Points" over Total/Start %/GS for a while after a column trim removed the three columns that had made the word shared, which is precisely the drift the rule exists to catch.
- **Caps are never interactive.** Sorting stays on the label tier; a clickable cap implies sorting a group, which is not a thing.

Mobile is unchanged and needs nothing: below the breakpoint an entry is an `EntryCard`, whose `MetaLine`/`Meta` already label every figure — that is the same grouping problem solved a different way.
