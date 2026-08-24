A sortable column header — put it inside a `<Row variant="head">` cell.

```jsx
<Row variant="head" cols="minmax(0,1fr) 96px 96px">
  <SortButton sort="none" onClick={() => sortBy("name")}>Franchise</SortButton>
  <SortButton sort="descending" align="right" onClick={() => sortBy("pts")}>Total pts</SortButton>
  <SortButton sort="none" align="right" onClick={() => sortBy("val")}>Trade value</SortButton>
</Row>
```

Sorting a ledger must reorder BOTH bodies — the desktop rows and the mobile `EntryCard`s. Reordering only the rows desynchronises them, which is invisible on desktop and wrong on a phone.

The inactive mark is **invisible**, not dim, and appears on hover or keyboard focus — ten arrows on a ten-column ledger is nine arrows saying nothing, and on a real board that noise plus each column's definition trigger re-jumbled a header a naming tier had just been added to fix.

Reveal it with **opacity only**. The mark's box is always reserved; collapsing it shifts the label 12px sideways on hover. Hiding the mark buys quiet, not room — cut the track to fit label + mark + trigger regardless.

`aria-sort` does **not** belong on this button: it is valid only on `columnheader`/`rowheader`/`gridcell`, so on `role="button"` it is silently dropped. Put it on the wrapping header cell. A ledger once shipped with no sort state announced at all because it lived here, and the tests asserted on the button too, so they stayed green.

