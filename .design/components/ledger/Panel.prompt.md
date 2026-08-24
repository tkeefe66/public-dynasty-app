The desktop ledger container — a solid card holding `Row`s.

```jsx
<Panel>
  <Row variant="head" cols="minmax(0,1fr) 96px 96px"><span>Franchise</span><span>Total pts</span><span>Trade value</span></Row>
  <Row cols="minmax(0,1fr) 96px 96px"><Name>Okafor</Name><Figure value={1688} /><Figure value={2880} /></Row>
  <Row variant="total" cols="minmax(0,1fr) 96px 96px"><span>All 12</span><Figure value={18240} /><Figure value={0} /></Row>
</Panel>
```

Pair it with a `CardList` of the same data for narrow widths — `Panel` is the `.fx-desk` body, `CardList` the `.fx-mob` one. Every interaction (sort, filter, collapse) must drive both.
