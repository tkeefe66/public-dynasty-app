A magnitude bar in a sunk track. Replaces Agate's `InkBar` — under Agate bars had to be ink, because a coloured pixel could only ever mean a signed figure.

```jsx
<Bar value={72} max={100} />
<Bar value={3940} max={4000} signed />
<Bar value={-1790} max={4000} signed />
```

Signed bars use `--pos-bar`/`--neg-bar`, weight-matched so neither hue reads as "more" at equal length. A negative bar is solid and grows leftward from the centre — a hollow outline disappears at the 3-8px widths that actually occur.
