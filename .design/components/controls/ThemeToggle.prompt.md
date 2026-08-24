The Light / Dark control. Belongs in the right-hand group of `TopBar`.

```jsx
<ThemeToggle value={theme} onChange={(t) => {
  setTheme(t);
  document.documentElement.setAttribute("data-theme", t === "dark" ? "dark" : "");
}} />
```

This is the one control at 30px rather than 44px: it sits in a 44px chrome strip where a 44px pill would define the strip's height. Dark is a first-class ground, not an inversion.
