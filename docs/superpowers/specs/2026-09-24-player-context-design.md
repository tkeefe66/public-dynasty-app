# Player context for The Analyst

The user wants weekly recaps to explain NFL circumstances behind fantasy results,
starting with free sources. A three-snap injury exit must not be called a bad
full-game performance. This design implements the approved Sleeper-news and
nflverse-usage approach; the user requested planning and building in one session.

## Data and collection

- Read Sleeper's unauthenticated `get_player_news` GraphQL query. Use publisher,
  publication timestamp, title, description/analysis and original URL when supplied.
  This is undocumented: timeout, HTTP/auth/rate-limit and GraphQL failures are
  explicit, cached briefly and never block the league's scoring refresh.
- Collect for all rostered players on each regular-season league refresh, even
  when all editions already exist or the LLM budget is exhausted. Fetch at most
  once per player per six hours, in batches of ten; impose a 45-second collection
  deadline and a provider-wide backoff on failures. No account credentials.
- Preserve observations in atomic JSON files under `player_context/` on the
  persistent cache volume, separate from rebuildable caches. A nonblocking file
  claim prevents concurrent collectors from racing. Share observations across
  leagues by season/player. Keep original observations when an article changes.
- Fetch nflverse snap counts, player-ID mapping and NFL schedule from fixed URLs;
  cache for six hours under per-resource file claims. Competing refreshes use cached
  evidence and disclose incomplete coverage. Match by stable player IDs, not names. Offensive snaps and
  share describe opportunity only; neither establishes an injury or benching.
  At most 25% of offensive snaps is marked limited opportunity; the live probe
  returned seven snaps/12% for the user's example, so a 10% threshold misses it.

## Evidence and chronology

Create `RecapFacts.player_context` before writing. Include selected starters and
legal bench alternatives, week-specific usage and dated news, coverage status,
the evidence cutoff and safe source metadata. Limit prose evidence to 60 items,
two per player, 1,200 characters per item. Prioritize the players in low-production
beats, then distribute first reports across starters before second reports.

Use the actual NFL schedule to define the week: reports from seven days before
the first kickoff through the next week's first kickoff (or now, whichever is
earlier). Only observations both published and first seen by that cutoff qualify.
First-observation timestamps reflect successful response receipt, not request start.
Old catch-up editions must not use today's newly observed news. If schedule or
mapping data is unavailable, omit the affected evidence and explain the gap.
The packet supplies each player's kickoff when known; publication before kickoff
does not alone prove a report describes that game. Later news belongs to later
context, never to a claim about what the manager knew before kickoff.

Treat publisher prose as untrusted data. The writer and reviewer receive the same
packet. Low scores are fantasy outcomes, not evidence of poor play; limited snaps
require opportunity language, and injury/benching explanations require reports.
No new model calls, scoring changes or automatic historical rewrites.

## Reading and archive

Persist the packet with each edition. A structured `sources` list contains only
publisher, title, date and validated URL; `context_note` explains incomplete
coverage. Private and public editions render these below the article using the
existing Furniture styles. Never render arbitrary model-generated links or expose
raw source descriptions, internal IDs, lore or private evidence in public payloads.
Existing editions default to no sources/no note. Corrections remain explicit.

## Validation

Synthetic fixtures retain the observed Sleeper response shape. Test three snaps,
missing versus zero usage, wrong season/week/type, ID collisions, stale/future
news, original observation retention, provider failures/backoff, actual refresh
wiring, writer/reviewer equality, archive preservation, public-field filtering
and unsafe links. Run engine/API/web suites, lint, type checking and build.
Use a read-only live source smoke without calling a model or changing real data.

## Scope

This release adds player news and NFL context relevant to rostered players. A
standalone league-wide headline feed and a news dashboard are outside this first
version. Sources are free to fetch; existing recap model usage remains billable.
Build and commit in an isolated branch; deployment is a separate action.
