# Owner profiles — interview notes

Source of truth for `lib/swagger.ts` OWNERS config. First names only in the UI.
Heat: full filth. Personalization: full rival-aware.

## REQUIREMENT: editable in-app
Profiles must be editable from the web app and persist (rosters + dynamics change
over time). This interview seeds the defaults; the in-app editor is the live
source of truth. Needs: backend store (JSON in cache dir) + GET/PUT API + an
editor UI. Build after the interview.

## Data model (locked)
- `winName` / `lossName`: name shown by context. Verdict winner slot → winName,
  loser slot → lossName. Most owners: same for both.
- `rivals: string[]` — multiple rivals allowed. Rival-aware verdicts get extra spice.
- `archetype` — short identity / one-word read.
- `roast` — signature joke(s) the league rides him for.

## Roster (12, first names)
Tom · Joey/Jory · Bobby · Amir · Mike · Oliver · Smitty · Parker · Brian · Cormac · Chris · John

NOTE: API returns Sleeper display names; build alias map (Sleeper handle → first
name) once the cache warms with real data.

---

## Joey  ("Jory")
- **winName:** Joey   **lossName:** Jory  (show Joey when he wins, Jory when he loses)
- **archetype:** The Trade Machine
- **read:** Trades constantly. Sees angles nobody else does — thinks he's
  fleecing you, usually getting fleeced or chasing dumb short-term moves.
- **rivals:** Tom  (+ likely more — TBD)
- **roast:** drafted Jason Witten when Witten was retired. His trades in general
  are the running bit.

## Bobby
- **winName:** Bobby   **lossName:** Robert
- **archetype:** The Degenerate (gambler — always posting betting slips)
- **read:** Not many enemies. First to laugh at Amir.
- **rivals:** Amir
- **roast:** The Cormac trade — Cormac gave up on the league and shipped all his
  good players to Bobby for basically nothing; league had to REVERSE it. Bobby's
  a bitch for letting it happen / taking it.

## Amir
- **name:** Amir (no flip)
- **archetype:** The Fool / clueless rebuilder
- **read:** Clueless early, traded his whole team away, now in epic rebuild mode.
  Foolish but doesn't get roasted too often.
- **rivals:** Bobby
- **roast:** traded away his whole team → perpetual rebuild.
## Mike
- **winName:** Mike   **lossName:** Michael
- **archetype:** The Loaded One / fleecer-in-chief
- **read:** Team is beyond stacked / insane — because Joey and Amir basically
  traded him their teams for nothing. Success has an asterisk.
- **rivals:** TBD
- **roast:** his stacked roster is bought, not built — fleeced Joey & Amir.

NOTE: "government name when you lose" is a recurring flip pattern
(Joey→Jory, Bobby→Robert, Mike→Michael). Offer it as the default suggestion
for each remaining owner.
## Oliver
- **winName:** Ollie   **lossName:** Oliver
- **archetype:** The Lurker / Terminally Online
- **read:** Super quiet in chat, few trades, mediocre team. Main contribution is
  Twitter links — everyone thinks he's on Twitter way too much.
- **rivals:** none
- **roast:** posts nothing but tweet links; terminally online.
## Smitty
- **winName:** Smitty   **lossName:** Brendan
- **archetype:** The Needler / bully of the weak
- **read:** Always down to rag on Joey and Amir. Mainly only trades with those two.
- **rivals:** Joey, Amir
- **roast:** not big roasts; just the constant Joey/Amir ragging.
## Parker — TBD
## Brian — TBD
## Cormac  (seed from Bobby's answer — confirm later)
- the guy who "gave up on the league" and dumped all his good players to Bobby
  for nothing (trade got reversed). Checked-out / quitter archetype?
## Chris — TBD
## John — TBD
## Tom (you) — TBD
