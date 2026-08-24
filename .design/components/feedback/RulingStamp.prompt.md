A trade ruling with the verdict as the headline.

```jsx
<RulingStamp
  verdict="Ruling"
  winner="Reznik"
  detail="Won four of five lenses, by 304 started points and 3,940 Trade Value."
  tag="Lopsided"
/>
```

The winner and margin come first; lens-by-lens detail goes in a `Panel` underneath. Never render "KTC" — the metric is called **Trade Value**.
