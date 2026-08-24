One entry as a card — what a ledger row becomes at or below 700px. This is the decided answer to the mobile split, not an alternative to it.

```jsx
<CardList>
  <EntryCard variant="mine">
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <Name>Okafor</Name><Figure value={1688} size="15px" />
    </div>
    <MetaLine>
      <Meta label="Record">58-45</Meta>
      <Meta label="vs Slot" tone="pos">+3,940</Meta>
    </MetaLine>
  </EntryCard>
</CardList>
```

Why a card and not a narrower row: a row is clamped to the rule pitch, so a two-line entry became two rules and a divider cut a franchise in half. A card's edge IS the entry boundary.

`Meta` tints only the value — the label stays dim. Each fact is `nowrap` so it wraps whole.
