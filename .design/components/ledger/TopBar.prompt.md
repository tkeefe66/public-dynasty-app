The one chrome strip. Every screen gets exactly this — there is no second nav and no ink app bar.

```jsx
<TopBar
  league="Bloodbath Dynasty"
  items={[
    { label: "Dashboard", icon: "table", on: true },
    { label: "Trades", icon: "swap" },
    { label: "Franchises", icon: "season" },
    { label: "Bets" },
    { label: "How this works" },
    { label: "Settings" },
  ]}
  right={<ThemeToggle value={theme} onChange={setTheme} />}
/>
```

The league sits beside the wordmark, not in the right group: Trades, Bets and Franchises have no masthead, so it is the only thing telling you which league you are in. Wraps at narrow widths rather than scrolling.
