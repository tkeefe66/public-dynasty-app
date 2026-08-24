Every number in the product. Tabular mono; signed values get colour, unsigned ones never do.

```jsx
<Figure value={1688} />
<Figure value={3940} signed />
<Figure value={-1790} signed />
<Figure value={161.4} dp={1} suffix="pts" />
<Figure value={null} />
```

`signed` is for a margin or a delta only — a rating, a record or a count is ink. Zero and absent both render `--dim`, absent as an em dash. Above ~13px the `--pos`/`--neg` pair fails contrast; use `GradeLetter`'s ramp or `.pos-s`/`.neg-s`.
