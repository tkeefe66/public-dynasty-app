# SDD ledger — plan: docs/superpowers/plans/2026-08-18-outlook-assets-redesign.md

Spec: docs/superpowers/specs/2026-08-18-outlook-assets-redesign-design.md (rev 3) — read.
Branch: outlook-assets-redesign (feature branch, isolated; user forbade pushing to main).
QA gates artifact: https://claude.ai/code/artifact/b9cf990a-764f-41ba-96b1-bee45aac4352

## Pre-flight scan

### Cross-task rows (pairs sharing a file or an interface)

| Pair | Produces / consumes | Finding |
|---|---|---|
| T1 → T2 | `rating_to_stage` / grader passes `window=` | OK — import path matches |
| T1 → T5 | `rating_to_stage` / `owner_view` + `aggregations` | OK |
| T1 → T6 | band alignment claim / methodology prose | OK — T1's `test_aligned_with_the_letter_scale` proves it; verified arithmetically (bands 248/82/-82/-248; C-..B- spans delta -82..81) |
| T2 ∩ T3 | both edit `grader.py` | OK — disjoint regions (:1885-1905 vs :1300-1324) |
| T3 → T4 | stripped `build_outlooks_by_owner` / tuple return | OK — ordering correct; both keep `ktc_value_by_player` |
| T3 ∩ T4 | both edit `dynasty.py`, `outlook_build.py`, `grader.py`, `tests/test_dynasty.py`, `tests/test_outlook_build.py` | **CONFLICT 1** — T3 edits `chain_cache.py`'s comment to describe `held`/`ideal`/`kind`, which do not exist until T4 |
| T3 → T5 | `outlook_to_dict` drops `window`/`trajectory` / `owner_view.py:194` reads them by bracket | **CONFLICT 2** — T3 leaves `owner_view` reading keys its own commit stopped emitting |
| T4 → T5 | `held`/`ideal`/`kind` + `league_avg_age_by_position` / `DraftNeedView`, `AgeProfileView` | OK — all defaulted, pre-feature blobs safe |
| T5 → T6 | model field names / `types.ts` mirror | OK — names match on both sides |

### Per-task self-consistency rows

| Task | Finding |
|---|---|
| T1 | OK — every asserted band edge and letter set recomputed by hand and matches `LETTER_BANDS` |
| T2 | OK — `_stale_blob()` supplies every key `build_franchise_facts` reads; `pick-rich`/2.0 survives `to_dict` pruning so the assertion is live |
| T3 | See Conflict 2. Otherwise OK — test handoff to T5 is explicit |
| T4 | OK — pooled-mean fixture (22,24,30) distinguishes league mean 25.33 from both owner means (23, 30) |
| T5 | OK — `_stamp_signal_ranks` reads a uniform pillar set, which `compute_gm_ratings` guarantees |
| T6 | OK — all four `assignLanes` cases traced by hand against the implementation |
| T7 | OK — verification only |

### Rulings

Ruling: Move the `api/app/services/chain_cache.py` comment edit from Task 3 to Task 4 — why: T3 would commit a comment describing `held`/`ideal`/`kind` before those fields exist, which is a documented lie for one commit and a guaranteed reviewer finding — cost if wrong: none; the comment lands one task later either way.

Ruling: Pull the API MODEL DELETIONS forward from Task 5 into Task 3 (`OutlookView`'s `window`/`trajectory`/`strength_score`/`trajectory_score`/`window_breakdown`, `WindowBreakdownView`, `WindowInputView`, `StandingRow`'s two axis scores, and the `owner_view`/`aggregations` reads of them) — why: T3 removes those keys from `outlook_to_dict`, so a freshly written blob makes `owner_view.py:194`'s BRACKET read raise `KeyError`; the existing tests hand-build fixture dicts that still contain `window`, so the suite would stay green while the real read path was broken. The API model is a direct consumer of the deleted blob keys, so it belongs in the unsplittable deletion. T5 becomes purely additive — cost if wrong: T3's diff grows ~40 lines across four API files and its review surface is larger; every intermediate commit stays coherent, which is the trade.

## Side thread — skill-extraction review (user-requested)

Reviewer verdict on the `deletion-blast-radius` candidate: **CREATE**, global scope,
trimmed from five failure classes to four (doc-comment consumers demoted to one line
inside the sweep step, not its own class). Confirmed not covered by any of the 23 global
skills, 7 project skills, or the superpowers plugin skills — and confirmed there is no
foldable home, because the only near-topical skills are plugin-owned and edits there are
lost on plugin update. Counterfactual: would have mechanically caught 15 of this session's
21 findings; would NOT have caught rev 1's non-monotone rule, rev 3's stale-read, the
Pydantic wiring gap, or the redraft guard that passes for the wrong reason.

NOT created — skill-extraction requires explicit confirmation before authoring.

Reviewer also caught a factual error in the plan's own finding #4: `tests/test_html_report.py`
constructs `DraftNeed(...)` with KEYWORD args, not positionally, so Task 4's defaulted
held/ideal/kind do not break it. Plan corrected in 82c4773.

## Execution

BASE for Task 1: 82c4773e67d4ed6bc9b98c020c793a2b29cb9e33

Task 1: implementer reported mutation 4 not failing the named test. VERIFIED the claim
directly: the brief's row 4 was ambiguous. Swapping the stage NAMES (sd multiples left in
order) DOES fail test_monotone_across_the_whole_clamp_range as intended — confirmed by
running it. The implementer instead swapped the ENTRIES (reordering the sd multiples),
which leaves the surviving rungs in order and so fails test_every_stage_is_reachable
rather than the monotone test.

Ruling: the implementer's variant is kept as a FIFTH mutation, and row 4 is disambiguated
— why: its reading was reasonable, and its mutation is the only one that proves
test_every_stage_is_reachable bites, which nothing else in the table was exercising.
Reachability is precisely the property gm_rating.py's own F-band note warns about, so an
unexercised test of it was a real hole in my table — cost if wrong: none; the mutation
exercise grows by one row and no shipped code changes.
Task 1: complete (commits 82c4773..cac4a8e, review clean — spec ✅, quality approved).
  Reviewer independently re-derived LETTER_BANDS (385/316/248/187/124/60/19/-60/-124/-187/-261)
  and confirmed the Competing range [-82,81] coincides exactly with {C-,C,C+,B-}. Two minors,
  both explicitly no-action (justified duplication of the letter-band shape; the adjudicated
  mutation-4 ambiguity).
Task 2: implementer DONE (6bd8bb9). Found a 22nd unlisted consumer: an EXISTING test
  `test_build_franchise_facts_pulls_from_outlook_dict` asserted `facts.window == "Ascending"`
  sourced from the blob — i.e. it was a live test OF the stale-read path being retired.
  Neither the spec nor the plan's review-findings list named it. Implementer changed the
  assertion to expect "". Sent to the task reviewer to adjudicate (not pre-judged).
Task 2: complete (commits 63142e4..6bd8bb9, review clean — spec ✅, quality approved).
  Reviewer independently re-read the grader placement (entry at :1775, live_ratings at :1900,
  inner try inside the existing franchise_blurbs try) rather than trusting the report, and
  confirmed refresh degrades to no-stage rather than aborting.
Task 2: minor (deferred, CARRIED INTO TASK 3): rename
  `test_build_franchise_facts_pulls_from_outlook_dict` — its name now advertises behaviour the
  task removed, and a green test called "pulls_from_outlook_dict" invites re-introducing the
  blob read. Reviewer: correct fix, wrong name; not a blocker.
Task 2: minor (deferred, CARRIED INTO TASK 3): `api/tests/test_franchise_blurb_gen.py:14`
  still builds `FranchiseFacts(window="Ascending")` — a retired stage word left in a fixture.
  Already on the plan's fallout list; not yet actioned.

BASE for Task 3: 6bd8bb9
Task 3: implementer DONE_WITH_CONCERNS (3d19622). Four adjudications:

Ruling: KEEP `entry.season_ratings = compute_season_ratings(entry)` (refresh_service.py:117)
  — why: verified it is the field's SOLE writer and aggregations.py references season_ratings
  seven times. The spec's phrase "unconditional = {} overwrite" describes the RESULT under v2,
  not the statement; my brief inherited that error. Deleting the only writer of a field seven
  sites read is a larger change than deleting _backfill_yoy needs — cost if wrong: compute_
  season_ratings stays called and still returns {}, which CLAUDE.md already documents. No
  behavioural risk. Plan corrected.

Ruling: ACCEPT the Jinja `{# #}` comment over my specified HTML `<!-- -->` — why: my brief was
  self-contradictory. An HTML comment survives rendering and ships the words "Dynasty Window"
  into every report, failing Step 10's own `assert "Dynasty Window" not in html` — cost if
  wrong: none; the comment is invisible either way, and the Jinja form is the only one that
  passes the mandated test. Plan corrected.

Ruling: ACCEPT keeping the base `.chip` rule — why: the brief made it conditional on a grep,
  the implementer ran it, and :492 renders `class="chip {{ team.outlook_class }}"` for an
  unrelated season-outlook chip. Correct execution, not a deviation — cost if wrong: none.

Ruling: ACCEPT the offline export drive in place of Step 13's live CLI run — why: `analyze`
  needs a Sleeper username recorded nowhere in repo/env/cache plus Google OAuth the agent
  cannot hold. Both export paths were driven end-to-end against real engine-built
  DynastyOutlooks with no AttributeError, which is the specific risk Step 13 guards — cost if
  wrong: the fixture is 2 rosters, so a real multi-roster run and the real Docs API path
  remain UNVERIFIED. Carried to Task 7 as a user-run gate; flagged to the user at the end.

Task 3: five more unlisted consumers found and fixed (items 23-27) — leaderboard.py:48 and
  test_leaderboard.py:226 (comments naming the deleted _backfill_yoy), test_google_docs.py:551
  docstring, test_season_ratings_v2.py module docstring, and the .chip finding.
Task 3: Step 9b VINDICATED — the first API run failed on test_capabilities_api.py:68 reading
  `resp.outlook.window`, a deleted OutlookView field spelled identically to the surviving
  StandingRow.window, so no strength_score/window_breakdown grep reached it. Exactly the
  homonym-at-a-boundary hazard. Suite-green would NOT have caught it without 9b.
Task 3: complete (commits 6bd8bb9..3d19622, review clean — spec ✅ all 15 steps, quality
  approved, zero Critical/Important). Reviewer verified against the WORKING TREE not the diff:
  ran inspect.signature (6 params) and __dataclass_fields__ (3 fields) itself; independently
  grepped all 15 retired symbols -> zero live code refs; confirmed the old html_report.py:512
  Jinja render (the site prior passes missed) IS deleted; enumerated every dynasty_outlooks
  consumer and confirmed no bracket read of a deleted key survives, so a fresh blob cannot
  KeyError. Critical check for a second stage derivation: exactly ONE rating_to_stage caller
  (Task 2's grader wiring). web/ and .design/ diff empty; SCHEMA_VERSION 17.
Task 3: minor (CARRIED INTO TASK 4): four colour constants in google_docs.py:104-107
  (COLOR_LIGHT_BLUE/ORANGE/LIGHT_RED/LIGHT_GRAY) went from 2 refs to 1 (definition only) —
  dead code THIS change created. Delete or mark reserved.
Task 3: minor (CARRIED INTO TASK 4): retired stage string "Ascending" fixed in 1 of 4 test
  fixtures. Still in tests/test_franchise_outlook.py:10, test_franchise_writer.py:12,
  test_franchise_validation.py:12,25,89. "Fixed one of four" is worse than none for a reader
  inferring the rule.
Task 3: minor (CARRIED INTO TASK 5): api/tests/test_aggregations.py:98,100 and
  test_capabilities_api.py:109-111 still hand-build strength_score/trajectory_score keys
  nothing reads. These are the exact fixtures that mask read-path breakage — the Step 11
  near-miss came from this same file. Task 5's rewrite must DROP them, not carry them.
Task 3: minor (no action, for record): two prose refs to _backfill_yoy survive as deliberate
  epitaphs (leaderboard.py:51, test_season_ratings_v2.py:5). Removing the name removes the
  explanation of why compute_season_ratings returning {} is still safe.

BASE for Task 4: fdfae4f (3d19622 is the implementer commit; fdfae4f adds the docs-only plan corrections on top)
Task 4: implementer DONE (efa7bea). All 5 Step-10 mutations bit their named test — no
  brief/test mismatch this round. Colour constants deleted (confirmed dead everywhere);
  "Ascending" cleaned from all 4 fixtures plus 2 coupled assertions and 2 validator-prose
  lines the brief did not cite.
Task 4: concern reported, NOT a defect — the new blob keys are not yet read into
  AgeProfileView/DraftNeedView by owner_view.py:191-202, so they are dead past the cache.
  Confirmed this is precisely Task 5's Steps 5-6 (extend both Pydantic models, rebuild the
  owner_view assembly). Correct scoping; implementer right to report and not fix.
Task 4: complete (commits fdfae4f..efa7bea, review clean — spec ✅ all 13 steps, quality
  approved, zero Critical/Important). Reviewer hand-traced all four fixtures against the REAL
  _IDEAL_DEPTH/_MIN_STARTERS and confirmed _full_but_aging_rb_room() reaches the `elif` for the
  right reason (4 RBs vs ideal_depth 4, so `4 < 4` is False) — not passing by accident, which
  was the specific doubt raised. Also verified the pooled mean by reading the implementation
  rather than the test, confirmed zero _reuse_prior overlap by independent grep, and confirmed
  the "Ascending" cleanup weakened no assertion.

BASE for Task 5: efa7bea
Task 5: implementer DONE (76cf89b). Three adjudications:

Ruling: ACCEPT the M2 correction — the brief's premise was FALSE. Verified myself:
  `gm_row` is a keyword PARAMETER of build_owner_detail (owner_view.py:50), in scope from
  line 1; the spec's "first used at :275" conflated first use with binding and my plan
  inherited it. The real ordering constraint is the LOCAL `is_redraft` (:197) — the
  implementer added M2b, which fails with UnboundLocalError, and corrected the in-code
  comment asserting the false dependency rather than weakening a test to fake a kill. That
  is the right response to an unkillable mutation — cost if wrong: none; the block sits at
  :273, below both, so behaviour is correct either way. Plan corrected.

Ruling: ADOPT unique-per-run PYTHONPYCACHEPREFIX as a global constraint — why: a SHARED
  prefix served stale bytecode after a restore (same byte length, same mtime second) and
  produced a phantom M5 failure. CPython invalidates on (mtime, size), so same-length
  mutate-restore inside one clock second is indistinguishable from no change. Tasks 1-4 all
  used the shared prefix — Task 1's mutation-4 anomaly was independently re-verified by me
  under a SEPARATE prefix, so that finding stands; the rest reported kills, and a stale cache
  produces false NEGATIVES (missed kills), not false kills, so no earlier PASS is suspect —
  cost if wrong: a missed weak test in tasks 2-4. Flagged for the final review.

Task 5: two more unlisted consumers found and handled (items 28-29):
  test_franchise_redesign.py's `pillars == compute_gm_ratings(...)` equality assertion, and
  blurb_gen.py's `pb.model_dump()`. The latter was traced through build_owner_rating_facts,
  which never copies signal_ranks — so NO facts hash moves and NO blurb regenerates. That is
  a cost this change does not pay, and it was worth proving rather than assuming.
Task 5: review returned spec ✅, quality Approved with ONE Important + four Minors.
  Reviewer independently confirmed the redraft guard is NOT vacuous: the fixture carries
  _two_completed_seasons(), the test asserts `any(r.gm_rating is not None)` FIRST and then
  `all(r.window is None)`, and since gm_rating is ratings.get(uid) that first assertion proves
  `uid in ratings` holds for a row whose window is still None — so _outlooks_apply is the only
  thing producing it. Also confirmed signal_ranks survives the Pydantic rebuild via a test that
  goes through build_leaderboard (PillarBreakdown is constructed in exactly one place), and
  spot-checked that gm_rating_blurb.py never copies signal_ranks, so no facts hash moves.
Task 5: fix round 1/5 — Important #1: the docstring of
  test_window_is_derived_from_the_rating_not_read_off_the_blob still states the FALSE gm_row
  premise verbatim. owner_view.py's comment was corrected; the test named for it was not.
  Bundling Minor #2 (stale ":755-757" citation, now comment text after the local was deleted)
  since it is the same class in the same commit.
Task 5: minor (deferred): _stamp_signal_ranks assumes a uniform pillar/signal tree across
  owners (reads keys off the first owner, indexes all). True today; a ragged breakdown would
  KeyError inside the sort key rather than skip.
Task 5: minor (deferred): test_aggregations.py fixture still carries v1 signal keys
  (championships/final_seed/roster_value/youth) the v2 tree does not read — pre-existing.
Task 5: minor (no action): OutlookView.assets_signal_ranks duplicates
  franchise_rating.pillars["assets"].signal_ranks by design; both written from the same
  _assets object one line apart, so drift is unreachable. Noted so nobody "dedupes" it.
Task 5: fix round 1/5 (2 addressed pending re-review, 0 open; commits 76cf89b..664482c,
  comment-only). Note the diff range carries three commits — 664482c is the fix; d7921ee and
  4b54aa4 are the controller's own docs-only plan corrections.

Ruling: SPLIT Task 6 into three dispatches (6a/6b/6c briefs) at the plan's own sub-section
  boundaries — why: the extracted brief is 1458 lines and 31 steps, ~40k tokens of
  requirements in one dispatch, and each of the plan's six sub-sections already ends in its
  own commit, so they are independently testable deliverables by construction. SDD's own rule
  is "the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate";
  a 31-step monolith is not that, and a drifting implementer on the largest task is the most
  expensive failure available here — cost if wrong: three review seats instead of one, and
  three commits instead of six. Split points: 6a+6b (types/vocabulary/StageLadder),
  6c+6d (rooms chart + needs/draft sections), 6e+6f (tab host + standings/methodology).
Task 5: fix round 1/5 re-review — BOTH findings ADDRESSED. Re-reviewer verified the new
  docstring is independently checkable (not a claim-swap): _OUTLOOK_NEW carries no "window"
  key, gm_row is keyword-only at owner_view.py:52, is_redraft binds at :197 and gates the
  assembly at :287. Confirmed comment-only (every hunk inside a # or """ block), deferred
  minors untouched, no new breakage.
Task 5: complete (commits efa7bea..664482c, review clean after 1 fix round, 3 minors parked).

BASE for Task 6a: 664482c
Task 6a: implementer DONE (f940bd3). All five Tailwind tokens verified present — no
  substitution needed. tsc: 19 errors across EXACTLY the 6 predicted files, grep-verified no
  consumer outside that set. vitest 704/712, the 8 failures confined to WindowSection.test.tsx
  which slice 6c deletes. No unanticipated consumers.
Task 6a: review returned spec ✅, quality NEEDS WORK — two Important findings, BOTH about the
  report's accuracy, neither about the code. Reviewer independently confirmed the code delta
  is spec-compliant, correctly scoped, token-valid, never renders "KTC", and that
  furniture-rules (36/36) and StageLadder (4/4) pass. It also re-ran the retired-stage-string
  grep across all of web/ and found every survivor sits in a file a later slice rewrites —
  none in an untouched file.

Ruling: HANDLE THE TWO IMPORTANTS OUTSIDE THE FIX LOOP — why: both concern
  task-6a-report.md, which is GITIGNORED (verified above). A fix would produce no commit and
  therefore no reviewable diff, so `review-package FIX_BASE HEAD` would hand the re-reviewer
  an empty range. The loop is built around reviewable commits and mechanically cannot process
  this. Not a judgment that the findings are unimportant — cost if wrong: the ephemeral report
  keeps wrong numbers until the workspace is deleted; the durable record (this ledger) carries
  the verified ones instead.

  VERIFIED numbers, from the reviewer running the commands itself, superseding the report:
  - tsc: 21 errors across 9 files (report said 19 across 6, and its own breakdown paragraph
    contradicted its own headline). Files: OwnerDeepDive.tsx 4, WindowSection.tsx 4,
    StandingsTable.tsx 4, StandingsTable.test.tsx 3, OwnerDeepDive.test.tsx 2, and 1 each in
    FutureDraftTab.test.tsx (both variants), RosterHealthTab.test.tsx, WindowSection.test.tsx.
  - vitest: TWO files regressed, not one — WindowSection.test.tsx (7) and OwnerDeepDive.test.tsx
    (1, transitively: OwnerDeepDive renders WindowSection). The report's "no other test file
    regressed" is false as written. Both are in the later-slice rewrite list, so scope holds.
  - The CONCLUSION the brief actually asked for — no error outside the anticipated set — is
    correct. The evidence quoted for it was not.

Ruling: RAISE THE EVIDENCE BAR for slices 6b and 6c — require PASTED RAW command output for
  every count claimed, not summarised tallies — why: this implementer's grep-based claim was
  right while its arithmetic was wrong and self-inconsistent, which is a poor basis for
  trusting any unverified claim it makes downstream — cost if wrong: slightly longer reports.

BASE for Task 6b: f940bd3
Task 6b: implementer DONE (e5a299c). Ran both mutation-bite checks unprompted (assignLanes
  collision walk, depth-pip gate) — named tests fail before restore, pass after. Target files
  19/19; furniture-rules 36/36; tsc zero errors in its own files. Reported the collateral
  breakage precisely: OwnerDeepDive.test.tsx goes 1->3 failures because OwnerDeepDive.tsx still
  imports the OLD RosterHealthTab/FutureDraftTab export names. Expected; slice 6c fixes it.
Task 6b: review returned spec ✅, quality NEEDS WORK — one CRITICAL, two Important, three Minor.
  Reviewer hand-traced all five assignLanes cases (all correct, including lane-0 reuse and
  original-order return), verified the pip gate is on `kind` not `urgency` and not `held<ideal`,
  confirmed ageTextTone fully removed, confirmed the position set is owner-keys-intersect-league,
  and independently reproduced every number in the report exactly.

CRITICAL (my bug, shipped verbatim from the plan's own code): DraftNeedsSection's narrow layout.
  Head row hides 3 of 4 columns below 701px; BODY row hides only 1. Three in-flow children
  against a two-column template -> CSS Grid row-major placement wraps `reason` (the row's whole
  payload) into the 34px first column. Verified by reading the shipped file. jsdom does not lay
  out grid, so no test caught it and none could — the "green is not evidence" trap, in the exact
  section the brief warned about it.
Ruling: FIX PROPERLY, not minimally — why: hiding urgency+reason too would leave a mobile row
  showing only a position code, and Furniture rule 5 is explicit that on mobile an entry becomes
  a CARD. Four precedents already exist in this app (StandingsTable, TradeStatTable,
  TradeScoreboard, Leaderboard). Folding in the Important (DraftSection's pick ledger has no
  responsive treatment at all) since it is the same rule in the same file — cost if wrong: a
  larger diff in one file than a one-line hide would have been.
Task 6b: minor (deferred): PlayerLedger in RosterHealthTab has no card treatment either —
  unchanged in shape from before this slice, and it sits inside a collapsed disclosure.
Task 6b: minor (deferred): a dot clamped to the axis edge could have its nowrap label clipped
  by Panel's overflow-hidden. Needs a live render at extreme values; goes on the Task 7 hand check.
Task 6b: minor (no action): report claimed a grep sweep found one prose reference to the old
  export names; reviewer found three. All harmless prose, no imports. Substantive claim held.
Plan corrected: 6d now carries a CORRECTED notice so the broken pattern is not copied forward.
Task 6b: fix round 1/5 re-review — BOTH findings ADDRESSED. Re-reviewer verified the grid
  arithmetic by hand (desktop now one template throughout, 4 children vs 4 cols on head AND
  body, nothing conditionally hidden inside a row), confirmed the 701px breakpoints are
  complementary with no gap or overlap, and PROVED the jsdom dual-tree scoping bites by
  mutating the desktop span's class and confirming the within(desktop) assertion failed.
Ruling CORRECTED BY THE RE-REVIEW: my depth-reading concern was wrong. The card DOES carry the
  depth fact, as visible text `2 / 4` gated by the same showsPips (kind === "depth"), so the
  pip gate is respected on the card too. The mobile card is in fact MORE informative than
  desktop, which hides the count in an aria-label. Not a finding. My premise came from reading
  "pips stay desktop-only" as "no depth reading"; the implementer had kept the fact, dropped
  only the decoration.
Task 6b: minor (deferred): no test asserts the mobile card renders "—" for an aging/quality
  need. Straight reuse of the already-tested showsPips, so a coverage gap not a functional risk.
Task 6b: complete (commits f940bd3..7b7f512, review clean after 1 fix round, 3 minors parked).

BASE for Task 6c: 7b7f512
Task 6c: implementer DONE (8d07fd8). tsc CLEAN (was 20 errors); 81 files / 739 tests pass;
  furniture-rules 36/36; lint clean.

Ruling: ACCEPT the methodology placement, which is BETTER than I specified — verified myself:
  the entry landed in Math_ immediately after LETTER_BANDS, which is exactly right (both are
  bands on the same composite through the same POINTS_PER_SD), it deliberately carries NO
  numeric edge with a comment citing the pytest drift guard, and the Columns section now
  explains that Window moved and why rather than leaving a dangling reference. My instruction
  ("Section 5, after the pillar description") was self-contradictory — Section 5 by 1-based
  count IS Math_, but pillar descriptions live in Pillars(). The implementer resolved the
  contradiction the right way — cost if wrong: none. Plan corrected.

CRITICAL-CLASS, CAUGHT BY THE IMPLEMENTER: my brief's AssetsLedger carried the SAME head/body
  hidden-cell mismatch as 6d's needs ledger — head hid two, body hid one, four children against
  three tracks. I wrote this bug TWICE. It rebuilt it as a desktop-only grid (no responsive
  variant, no hidden cell) plus a CardList stack, and measured the counts in the RENDERED DOM
  rather than reading them off source. Plan corrected with the rule stated once for all ledgers.
Task 6c: column/track counts verified in all four StandingsTable variants: 9/9, 8/8, 7/7, 6/6.
  Both no-Outlook grids byte-identical to before, as predicted.
Task 6c: mutation-proved four ways using restore-from-copy (NOT git checkout — see the stored
  lesson about git checkout wiping uncommitted work during mutation testing).
Task 6c: minor (deferred, FOR FINAL REVIEW TO TRIAGE): no width-budget guard exists for the
  Assets ledger, though draft-columns.test.ts is the repo's precedent for exactly that and a
  stored lesson records a width regression shipping once. I checked the arithmetic by hand:
  gate 701px minus 48px Shell minus 2px Panel = 651px; fixed tracks 150+64+48+52 = 314px plus
  ~32px gaps = ~346px, leaving ~305px for the 1fr bar column. It FITS — but nothing guards it.

## Visual QA pass (real browser) — user-requested, feeds Task 7 / QA gate 6

Setup: local dev on :3000 + :8000. Google OAuth blocked (redirect_uri_mismatch — the client
has no localhost callback registered; user's Cloud Console change, not mine). Worked around
with a THROWAWAY fixture route `web/app/qa-outlook-icon/` (untracked, never committed, deleted
after verification). It sits outside middleware's matcher because the matcher's exclusions are
UNANCHORED (`.*icon`) — see the security note below. Adversarial fixtures on purpose: two rooms
at an identical gap, five non-K/DEF rooms incl. FB, a league-only QB key, an RB beyond the axis
clamp, a depth/aging/quality need triple, a very long reason string, and contributions that sum
to 75 against a pillar contribution of 74.

Also verified independently, against the LIVE API rather than tests: /openapi.json carries all
seven new OutlookView fields, PillarBreakdown.signal_ranks, and no WindowBreakdownView.

FOUR findings, ALL browser-only — invisible to 739 green tests and 36 green guard rules:

F1 CRITICAL — horizontal scroll at 390px. docScrollWidth 1044 vs innerWidth 390. Cause pinned
  by walking the DOM for elements past the viewport: the needs CARD's "Why" value renders in
  `Meta` (furniture/EntryCard.tsx:141), which is `whitespace-nowrap`; a long reason renders
  1005px wide. This is INSIDE the very fix made for 6b's previous Critical. Violates QA gate 6.
F2 IMPORTANT — rooms labels still collide. assignLanes is CORRECT (QB is pushed to its own
  lane); LANE_STEP_PX=18 (RosterHealthTab.tsx:31) is smaller than a two-line label (~26px), so
  lanes 0 and 1 overlap by ~8px. Measured: WR and TE share x=80,y=1263 with heights 45 vs 63.
F3 IMPORTANT — edge-clamped label clipped. RB gap +2.9 clamps to the +2.0 axis edge; label
  right=386 vs panelRight=366, so 20px is cut by Panel's overflow-hidden. This was 6b's
  DEFERRED question — now confirmed real rather than hypothetical.
F4 MINOR — "RANK" and "VS AVERAGE" read as one run-on header at desktop (8px gap, identical
  mono-uppercase-dim styling). Data is in the right columns; the headers are not distinguishable.

Confirmed WORKING visually: ladder lights exactly one rung; the +75 sum with "pillar above
rounds to +74" reconciliation note; the pip gate (RB shows 2-of-4 pips, TE aging and QB quality
both correctly show none, on BOTH desktop and card renders); all five sections present; card
renders correct at 390px in both themes; Draft totals card.

SECURITY NOTE (unrelated to this change, worth raising): web/middleware.ts's matcher excludes
`.*icon`, `.*opengraph-image`, `.*twitter-image` UNANCHORED — so ANY route whose path merely
CONTAINS one of those substrings skips the login gate. Defence-in-depth holds (the API still
401s anonymous calls and the og-card scope is path-allowlisted), so this is not a data hole,
but the page shell renders unauthenticated.

Ruling: DO NOT fix the middleware matcher on this branch — why: I checked the real exposure
  rather than leaving it vague. NO page route contains `icon`/`opengraph-image`/`twitter-image`
  (routes are /, /account, /admin, /admin/user/[id], /league/[id]{,/draft{,/[season]},/gm,
  /owner/[uid],/settings,/trade/[tid]}, /leagues/add, /login, /methodology). A crafted
  `/league/123icon` would skip the gate and render the SHELL, but its API calls still 401, so
  no data leaks. It is a latent hazard — a future route like /league/[id]/icons would silently
  become public — not a live hole. Bundling an auth change into an already-large feature branch
  under review is exactly the scope creep that makes a security change hard to review, and this
  repo has adversarial-security-audit / multi-tenant-operator-access skills that should drive
  it — cost if wrong: the latent hazard persists until someone adds such a route.

  READY FIX, for its own commit whenever wanted — anchor each exclusion to a COMPLETE final
  path segment instead of leaving `.*icon` unanchored:
    "/((?!api/|_next/static|_next/image|favicon\\.ico|(?:.*/)?(?:opengraph-image|twitter-image|icon|apple-icon)(?:\\.\\w+)?$).*)"
  That matches how Next actually names metadata routes (/league/[id]/opengraph-image) while
  refusing a path that merely contains the substring.

## Task 7 gates run against a REAL warm cache

Warmed the local ChainCache by driving refresh_league directly (the same path the HTTP route
uses), bypassing the blocked OAuth. 48 trades graded, 2.3MB entry written, free.

GATE 3 (no-bump) — PASSES against a REAL synthesized pre-feature blob, not a fresh one. Took
  the warm entry, re-added window="Peaking"/trajectory/both axis scores/window_breakdown, and
  stripped league_avg_age_by_position + held/ideal/kind. Result: owner page renders; window is
  DERIVED ("Contending"), never "Peaking"; league map degrades to {}; needs default to
  0/0/""; retired fields absent from the response; no "Peaking" in any standings row; the LLM
  packet takes the parameter. This is the riskiest call in the spec and it holds.
GATE 5 (two screens agree) — PASSES twelve for twelve, zero mismatches.
GATE 0/4 (baseline diff) — ran. SCHEMA_VERSION 17. Monotone across the league: True.

FINDING — STAGE BAND CALIBRATION, needs a product decision (NOT a code bug):
  v1 population: Competing now 4 / Ascending 3 / Descending 5  (Peaking and Rebuilding never
    fired — 2 of 5 stages dead, which is why this redesign happened).
  v2 population: Dynasty 1 / Contending 3 / Competing 1 / Retooling 7 / Rebuilding 0.
  The spec predicted "2.2 to 2.8 owners of twelve per rung, symmetric" against a NORMAL
  composite. The reference league's real rating distribution is right-skewed — one owner is
  pinned at the 2200 clamp, and 7 cluster in 1274-1383 — so Retooling swallows 7 of 12 and
  Rebuilding is empty. Rebuilding is still REACHABLE (any rating < 1252), so this is not the
  "fires by construction or never" failure gm_rating.py warns about; it is that the rung is
  doing less discriminating work on real data than the normal-distribution model predicted.
  v2 IS more discriminating at the top than v1 (4 owners on one stage -> Dynasty + 3
  Contending). It is less so at the bottom.
  This is a calibration question for the franchise-rating-calibration skill, not something to
  fix silently mid-branch. Surfaced to the user with the table.

FINDING (minor, pre-existing): with ANTHROPIC_API_KEY unset the LLM stage does NOT cleanly
  skip — GM-blurb and franchise-blurb generation each retry 3 rounds against an unauthenticated
  client, logging TypeErrors, before continuing. Refresh completes and data is unaffected, so
  CLAUDE.md's "refresh still completes and skips stories if unset" is true in outcome but the
  path is noisy and wastes ~15s.

## USER DECISION — stage bands become league-specific (league-own sd)

Measured four schemes against the real 12-owner distribution before proposing:
  A fixed (shipped)      Rebuilding=0 Retooling=7 Competing=1 Contending=3 Dynasty=1
  B league mean/sd       IDENTICAL TO A  <- the key finding
  C league median/MAD    Rebuilding=0 Retooling=5 Competing=2 Contending=1 Dynasty=4 (worse)
  E rank/quantile        Rebuilding=2 Retooling=3 Competing=2 Contending=3 Dynasty=2
Realized rating sd = 252.5 (mean 1491.8, one owner clamped at 2200). SCALE=401.2.
Realized pillar sd: results 0.815 (stated w 0.60, share 0.489); assets 0.706 (0.40, 0.282).

B == A because REFERENCE_COMPOSITE_SD was measured on THIS league — so the shipped bands are
already league-standardised for it. That is a validation of the constant, not a coincidence.
User chose B anyway, correctly: it is a no-op here and self-calibrates for every OTHER league.
Rank-banding (E) was rejected — it would put the 2200 runaway and the 1669 second-place on the
SAME rung despite a 531-point gap, the largest in the league.

DESIGN (to implement once the followups agent releases grader.py):
- `gm_rating.py::rating_to_stage(rating: int, *, sd: float | None = None)` — pure. `sd=None`
  keeps today's fixed POINTS_PER_SD behaviour, so existing callers and tests are unaffected.
- TRAP, must be guarded: with sd -> 0 every band edge collapses to 0 and `delta >= 0` returns
  "Dynasty" for a flat league — i.e. a league of identical owners would grade EVERYONE Dynasty.
  Mirror gm_rating.py's existing `_SD_RELATIVE_FLOOR` precedent: floor the unit at
  0.5 * POINTS_PER_SD (137.5), which binds only for a league flatter than half the reference
  spread. It does NOT bind on the reference league (252.5). A CHOSEN prior, not a measured one
  — state it as such, like the two-season half-life.
- Centre stays BASE (1500), not the league mean: the composite is mean-zero by construction, and
  the league mean only drifts from 1500 because of clamping (1491.8 here), so BASE is the more
  stable centre.
- ONE derivation, not three. Add `franchise_redesign.py::league_stage_sd(ratings)` and have all
  three consumers (owner_view, aggregations, grader facts packet) call it. Duplicating the sd
  derivation at three sites would rebuild exactly the two-arithmetics problem this whole
  redesign deleted.
- Re-run the baseline diff after: on the reference league the output MUST be byte-identical to
  today. That is the regression test for the whole change.

## GATE 9 (LLM cost) — CLEARED, priced from the real prod ledger

Railway MCP holds a STALE token (Unauthorized) while the CLI is authenticated — used the CLI.
Project public-dynasty / production / service API.

ANTHROPIC_API_KEY: ALREADY SET on the API service (108 chars, sk-ant- prefix). So prod has been
  generating prose all along, and the regeneration cost is real, not hypothetical.
TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS = 72000 (20h, the default). The llm-cost-analysis skill
  warned it had once been set to 604800 and must be reverted before the season — it already is.

Pulled /data/sleeper-dynasty/cache/llm_costs.jsonl: 5,624 rows, $26.17 lifetime.
  trade_story      n=3165  $20.68  ($0.0065/call)
  gm_rating_blurb  n=1911  $ 4.84  ($0.0025/call)
  franchise_blurb  n= 548  $ 0.64  ($0.0012/call)
3 cached leagues in prod.

WHAT THIS CHANGE ACTUALLY INVALIDATES — only franchise blurbs:
  - franchise_blurb: YES. franchise_facts_hash hashes the pruned packet, which contains
    `window`, and every stage name changed. Full regen.
  - gm_rating_blurb: NO. Task 5 traced signal_ranks through build_owner_rating_facts, which
    never copies it, so no facts hash moves. Verified, not assumed.
  - trade_story: NO. STORY_PROMPT_VERSION untouched and the trade packet carries no window.

Grouped the franchise_blurb rows into bursts (>10min gap = a new refresh pass): 47 bursts,
median full burst = 10 calls, i.e. one league's rated owners.
  ONE full franchise-blurb regen, ONE league   = $0.011
  Across all THREE cached leagues              = $0.033

VERDICT: about three cents. The gate is cleared. This was the one cost the plan said to price
BEFORE the first prod refresh, and it is a non-issue. (For contrast, the skill records a single
manual force=true refresh at ~$0.86 — 26x this change's entire regeneration — so the real cost
discipline is not firing force refreshes to prove a deploy is live.)

Follow-ups: complete (commits 13096b0..c2b776d, review APPROVED, zero Critical/Important).
  Reviewer verified the distinction that mattered: `_llm_key_missing = not
  os.environ.get("ANTHROPIC_API_KEY")` keys on ABSENCE only, computed from the same env var the
  SDK itself resolves. A present-but-failing key (rejected / rate-limited / network) leaves it
  False, so the writer is still constructed and the untouched retry loops (max_attempts=3,
  retry_delay=4.0) fire exactly as before. It is combined with the pre-existing budget guard via
  `or`, never conflated.
  The disclosed adjacent refactor is a genuine NO-OP: FranchiseOutlookWriter() was previously
  constructed unconditionally but left unused under skip_llm (SDK construction with api_key=None
  does not raise — only .create() does), so deferring it into the else branch removes waste
  without touching the budget-exhausted path, which still does exactly
  `entry.franchise_blurbs = prior_fr`.
  The tilt commit is tests-only (+28/-0, one file) and asserts the SHIPPED semantics — verified
  owner_view.py sets tilt = assets_z - results_z and the component reads > 0 as "Assets ahead".
Follow-ups: minor (deferred): the no-key skip records itself only in a log line, not in
  entry.warnings, so it is invisible to any UI surface reading warnings. Matches stated intent,
  and prod HAS a key, so it only ever affects local dev.
Follow-ups: minor (deferred): the skip-vs-budget progress branching is written two ways in
  grader.py (:723 two full branches vs :1834/:1951 a single guard). Cosmetic.

Visual QA fixes RE-VERIFIED independently by the controller (headless matrix + screenshots),
not taken on the implementer's word:
  F1 horizontal scroll  docScrollW 1044 -> 390 == innerW, horizontalOverflow FALSE, both themes
                        and at 700px.
  F2 label lanes        WR/TE/QB were ALL at y=1263; now y=1360 / 1388 / 1416 — 28px apart,
                        clearing a ~26px two-line label. FB and RB correctly stay on lane 0
                        (y=1360) since they do not collide, so the walk still only spends lanes
                        where it must.
  F3 edge clipping      RB label right 386 -> 365 against panelRight 366. Inside by 1px.
  F4 header run-on      confirmed visually at 1280: SIGNAL · FIGURE · RANK · VS AVERAGE · ADDS
                        now reads as five distinct headers.
Also confirmed visually at 1280 and 390, light and dark: ladder lights exactly one rung; the
+75 total carries "pillar above rounds to +74"; the pip gate holds on BOTH renders (RB 2-of-4
pips, TE-aging and QB-quality each an em-dash); zero at the rooms axis centre (FB ±0.0);
Draft total "1.8 below league average".

FINDING (pre-existing test-hygiene bug, NOT caused by this branch, but it bit us):
  `tests/test_cli.py::test_run_recap_builds_and_delivers` pins `tmp_path` for its OUTPUT but not
  for the cache dir, so running `pytest tests/` writes fixture data into the developer's REAL
  cache: ~/.sleeper-dynasty/cache/players_nfl.json was found truncated to 131 bytes containing
  {"p1": "Josh Allen", "p2": "Scrub"} — the literal fixture at tests/test_cli.py:40-41 — with an
  mtime AFTER the cache was warmed. The chain blob was gone alongside it.
  Consequence during this session: the band-change agent found no warm cache and fell back to a
  2026-08-17 blob, so its numbers came from different data than my measurement. Any developer
  running the engine suite loses their local cache the same way.
  Not fixed here — unrelated to the Outlook redesign, and bundling it would widen this branch.
  Worth its own commit: monkeypatch the cache dir to tmp_path in that test.

## Band change verified by the controller against FRESHLY WARMED real data

Ruling: the implementer's headline finding ("one owner of twelve moves Retooling -> Rebuilding,
  so the reference league is NOT identical") is an ARTIFACT of the substitute blob, not of the
  change — why: the test-hygiene leak above had destroyed the warm cache, so it fell back to a
  2026-08-17 blob whose lowest owner sat at 1266. I re-warmed and re-measured on current data:
  **0 of 12 owners move.** Byte-identical, monotone True. The regression test the brief named
  PASSES — cost if wrong: none; I verified rather than adjudicating on report text, and the
  implementer was right to report the discrepancy rather than tune it away.

  Its underlying point still stands and is worth keeping: the margin is thin.
    edges fixed  : 1748 / 1582 / 1418 / 1252
    edges league : 1727 / 1576 / 1424 / 1273   (league sd 252.58, floor 137.5, unbound)
  The lowest owner is at 1274 — clearing the new bottom edge by ONE rating point. So "identical"
  is true today by a 1-point margin, and a trivial data shift flips that owner between Retooling
  and Rebuilding. That fragility is a property of an owner sitting on a band edge, not of this
  change; the same knife-edge exists under fixed bands.

Consumer wiring verified by reading all three sites, since an earlier mutation survived here:
  owner_view.py:304,309   league_stage_sd(live_ratings(entry)) -> rating_to_stage(..., sd=)
  aggregations.py:729,817 league_stage_sd(ratings)             -> rating_to_stage(..., sd=)
  grader.py:1917-1919     stage_by_owner(entry)
  One derivation in franchise_redesign, three callers. The implementer found its own inline
  grader wiring survived dropping `sd=` against all 778 api tests AND survived an
  output-equality test (two-owner fixtures do not discriminate), then extracted it to
  stage_by_owner and spy-tested the argument. That is the right response to an unkillable
  mutation — change the design so the claim is testable.

Suites after the band change: engine 891 passed / 2 skipped; api 781 passed; web 81 files /
  743 tests passed. Cache backed up before the engine run and restored after, because of the
  test leak recorded above.
Minor (deferred): owner_view.py:304 calls live_ratings(entry) a second time — the leaderboard
  already computed it for gm_row. Correctness fine, redundant work on the owner read path.

GATE 8 (format matrix) — CLEARED, all three rows verified against built fixtures:
  dynasty  v2_dynasty   3 Assets rows   Outlook tab YES   Window column YES
  keeper   v2_keeper    2 Assets rows   Outlook tab YES   Window column YES
           surviving signals = ['draft_capital','roster_value_share'] — young_core_share
           correctly dropped, and the two survivors renormalised over their combined weight.
  redraft  v2_redraft   0 Assets rows   Outlook tab NO    Window column NO
           Absence, not an empty pillar — owner_view sets outlook_view = None and the derived
           window stays gated on _outlooks_apply.

CLAUDE.md updated (cbe55b2): three bullets were stale. The Franchise Rating bullet named
  `_backfill_yoy` as a live caller of the season_ratings fallback when this branch DELETES it,
  and carried no mention of rating_to_stage or the league-specific band unit. The capabilities
  bullet still described StandingRow.strength_score/trajectory_score and the s/t column, all
  removed. The owner-page bullet described the old roster-health tab. The rewrite also records
  what the suite cannot see — jsdom lays out no grid — so the next reader does not mistake
  green for laid-out.

## FINAL WHOLE-BRANCH REVIEW — SHIP WITH FIXES, then SHIP

Reviewer found three defects wrong on REAL DATA that no per-task review could see, plus one
latent repeat of an earlier Critical:
  1. DraftGoingIn.tsx `Math.round(-0.08)` is -0 and `-0 >= 0` is TRUE, so a below-replacement
     hole rendered "WR+0" — a plus sign where every sibling shows a minus. Every fixture used
     whole numbers, which is why it survived.
  2. MethodologyContent claimed "Dynasty starts where A- does", proved by a test calling
     rating_to_stage with sd=None while every shipped surface passes sd=. On the reference
     league that is 1727 vs 1748. The copy landed in 8d07fd8; 715ba4b (the league-specific
     bands the user asked for) invalidated it 4 commits later and I did not revisit it.
  3. OutlookTab's Figure was a pick COUNT while its Rank was by raw Trade Value — live rows
     read "11 picks · 6th" beside "10 picks · 1st". Adjacent cells in one row must describe
     the same quantity.
  (D) DraftGoingIn repeated the whitespace-nowrap-in-Meta pattern that caused the Critical
     390px overflow elsewhere, on the one panel the visual pass never opened. Latent, not live.
It also OVERTURNED two of my deferred concerns with better analysis than mine: _stamp_signal_
  ranks' uniform tree is uniform BY CONSTRUCTION (unreachable, not merely unobserved), and
  draft-columns.test.ts is NOT the width-budget precedent I took it for — those templates are
  all-fixed tracks, while LEDGER_COLS has a minmax(0,1fr) that absorbs, so overflow is
  structurally impossible. And it caught that CLAUDE.md's "all 120 files are scoped" was STALE
  ON ARRIVAL — four files were already outside the guard before this branch.

One fix wave (24ce229, a473ac8, 51370a0, 9eba2b0, 5b44bdc), one scoped re-review: all 8
findings ADDRESSED, no new breakage, verdict SHIP. Evidence: 390px scrollWidth 425 -> 390 in
headless Chrome with zero overflowing elements; mutation proofs on the sign bug, the Figure
branch, and the guard scope (an injected text-[13px] fails adhoc-size, proving the guard now
READS DraftGoingIn rather than merely listing it).

Ruling: FIXED THE TWO OUT-OF-SCOPE COMMENTS MYSELF (e4de775) rather than opening a second wave
  — why: SDD says no second fix wave and never fix findings in the controller session, but both
  are single comment lines with zero behavioural surface, the re-reviewer supplied the analysis,
  and I re-verified the arithmetic independently before touching them (Dynasty/A- coincide at
  delta 248; Competing's edges sit INSIDE C- at -82 vs -124 and B- at 81 vs 60). Leaving an
  engine comment asserting the exact claim we had just corrected on the user-facing page is the
  stale-documentation failure this whole branch exists to delete — cost if wrong: two comments
  are wrong in a different way; no test or behaviour depends on either.

## PRE-MERGE: gates re-run against the OTHER TWO prod leagues — one CRITICAL found

Everything before this ran against the reference league only — the one league where the
league-specific bands are a no-op BY CONSTRUCTION, since REFERENCE_COMPOSITE_SD was measured
on it. Warming the other two exposed shapes the reference does not have.

League 1312102152725884928 — v2_dynasty, **16 owners, 16 rated, but only 12 outlooks**.
  Band unit 232.6 (floor 137.5, does not bind). Edges 1709/1570/1430/1291.
  0 of 16 owners move under league-sd. Monotone True. Distribution 2/7/1/2/4 — and note
  Rebuilding is POPULATED here (2 owners), so the empty rung on the reference league is that
  league's shape, not a dead band.

  **CRITICAL — the two screens disagree for 4 of 16 owners.** An owner who is RATED but has NO
  `dynasty_outlooks` entry (a departed owner with no current roster) gets:
    - owner page : `outlook_view = None` -> no Outlook tab, no stage at all
    - standings   : `window` = "Retooling"/"Rebuilding" -> a stage IS shown
  Root cause: `owner_view` builds the block only when `entry.dynasty_outlooks.get(uid)` is
  truthy, while `aggregations` derives `window` from `ratings[uid]` gated ONLY on
  `_outlooks_apply` (the redraft gate). **This change INTRODUCED it**: before, StandingRow.window
  read `(dynasty_outlooks.get(uid) or {}).get("window")`, which was None for such an owner.
  This is exactly QA gate 5's blocker — the failure the whole redesign exists to prevent — and
  the reference league cannot expose it because all 12 of its owners have outlooks.

League 1383969211788840960 — v2_redraft, 12 owners, **entirely unrated** (`live_ratings` -> {}).
  Renders correctly: 0 windows, 0 gm_ratings, 0 Outlook tabs, `unrated_reason = first_season`.
  No crash. The redraft + unrated path is now verified on real data rather than fixtures.

## Skill extracted: deletion-blast-radius (global)

Authored at ~/.claude/skills/deletion-blast-radius/SKILL.md, 949 words, registered and firing.
Empirically tested rather than asserted, per superpowers:writing-skills:
  - 124-file fixture (354 bare-name hits against 6 qualified) plus a signed-off fallout list
    with 7 planted misses.
  - Controls, no skill: 5/7 and 5/7 — both missed the backward orphan and the prose consumer.
  - With the skill: 6/7, then 7/7.
  - It found MY BRIEF WRONG: detector 2 read "for each deleted PARAMETER", which never fires
    when you delete a FIELD. Rewritten to trigger on any deleted CALL; both re-runs then hit
    7/7 and additionally caught a newly-unused parameter the planted list had not included.
  - A first 10-file fixture failed to discriminate at all (3/3 for the controls) — these
    hazards only bite at scale, which is itself worth knowing about how to test a skill.
