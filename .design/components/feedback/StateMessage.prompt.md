An empty, error or not-found state — always with the one action that resolves it.

```jsx
<StateMessage
  title="No trades yet this season"
  body="Nothing has moved since the draft. Trades appear here within a minute of processing in Sleeper."
  action="See 2024 trades"
  href="/trades/2024"
/>
<StateMessage tone="error" title="Sleeper didn't answer" body="Their API timed out. Your data is safe; nothing was lost." action="Try again" />
```

Say what happened in the product's voice. "No data available" tells a reader nothing, and a state with no way out is a dead end.
