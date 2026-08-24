The action control — a stamp-filled primary or an outlined ghost, always at least 44px tall.

```jsx
<Button icon="swap">Read the ruling</Button>
<Button variant="ghost" iconAfter="forward">All trades</Button>
<Button disabled>Saving…</Button>
```

One primary per view: two stamp fills side by side make neither of them primary. For "out to a bigger view" prefer `MonoLink` over a second button. `href` renders an `<a>`.
