A stroked first-party mark — use for every icon in Furniture; there is no icon library and Lucide is banned by the app's drift guard.

```jsx
<Mark name="forward" size={12} />
<Button icon="swap">Trade ruling</Button>
```

Nineteen names on a 16px grid: `sort-desc`, `sort-asc`, `open`, `closed`, `forward`, `back`, `info`, `alert`, `done`, `close`, `add`, `light`, `dark`, `copy`, `share`, `swap`, `table`, `season`, `menu`. Adding one means drawing it in `fx-icon-paths.js`.

Agate's `Icon` is the same nineteen names CUT rather than stroked; it is still exported for `[data-theme="agate"]` surfaces. Do not mix the two on one screen.
