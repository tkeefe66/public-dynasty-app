The definition behind a label — attach one to every pillar and signal name.

```jsx
<Row cols="minmax(0,1fr) 60px">
  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
    Draft Skill
    <Tooltip title="Draft Skill" body="How much more your picks produced than the average pick at the same slot." formula="Σ(actual − slot expectation) / picks" />
  </span>
  <Figure value={72} />
</Row>
```

Two things that must hold: the panel is `position: fixed` so a `Panel`'s `overflow: hidden` cannot clip it, and the trigger's 26px target is deliberate — it sits inside a 34px rule, clears WCAG 2.5.8's 24px minimum, and must not be "fixed" to 44px.

Never ship a trigger with no definition. Hover opens on pointer devices; click toggles for touch and keyboard; Escape closes.
