One rule in a ledger. `cols` must be identical on the head row and every body row.

```jsx
<Row variant="head" cols="minmax(0,1fr) 74px 96px"><span>Franchise</span><span>Rec</span><span>Rating</span></Row>
<Row variant="mine" cols="minmax(0,1fr) 74px 96px"><Name>Okafor</Name><span>58-45</span><Figure value={1688} /></Row>
<Row variant="total" cols="minmax(0,1fr) 74px 96px"><span>All 12 franchises</span><span /><Figure value={18240} /></Row>
```

Two rules that have each been broken here: a `total` must be **recomputed from the visible set** when a filter changes, and it must **name** what it totals when the rows are an abbreviation. Never nest a `<button>` inside a row that is already a link.
