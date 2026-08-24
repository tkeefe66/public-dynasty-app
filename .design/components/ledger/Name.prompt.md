A franchise or player name, in the display face.

```jsx
<Row cols="minmax(0,1fr) 96px"><Name>Okafor</Name><Figure value={1688} /></Row>
<EntryCard><Name on="card">Okafor</Name></EntryCard>
```

Always this component, never a bare `<span>` with a font declared on the parent — a name that inherits its face from a row renders in Geist inside a card, which makes one franchise look like two designs.
