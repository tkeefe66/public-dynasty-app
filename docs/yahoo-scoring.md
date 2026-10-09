# Yahoo NFL scoring and threshold bonuses

The Yahoo adapter supports **74 of the 87 categories in the researched NFL catalog**. This change adds **20 category mappings** to the previous 54 and supports cumulative weekly bonuses on every mapped category. A bonus is represented by its actual target and point award; there is no fixed list of accepted yardage milestones.

These counts describe the current `_SCORING` table in [the Yahoo adapter](../src/sleeper_dynasty/api/yahoo.py), compared with the catalog preserved in [the public scoring evidence fixture](../tests/fixtures/yahoo/scoring_category_evidence.json). They do not establish support for every Yahoo setting, future category, player-position rule, or historical source record. The 13 unsupported catalog categories are listed below and still stop an import when they affect scoring.

## How bonuses are represented and scored

A league stores linear multipliers in `League.scoring_settings` and conditional awards separately in `League.scoring_bonuses`. Each [ThresholdBonus](../src/sleeper_dynasty/models/scoring.py) contains:

```json
{
  "stat_keys": ["pass_yd"],
  "target": 300,
  "points": 3
}
```

This is the application's normalized representation. It is not a captured Yahoo wire response.

The [weekly scorer](../src/sleeper_dynasty/engine/scoring.py) first prices the week's component statistics with their linear multipliers. It then evaluates each bonus independently:

```text
combined_stat = sum(this week's value for each stat_key)
if combined_stat >= target:
    add points once
```

The comparison is **inclusive**. Awards are **cumulative** and are added to the base score. A higher milestone does not replace a lower milestone. Yahoo's [official scoring FAQ][yahoo-help] explains that multiple reached bonuses stack; public [league settings][yahoo-settings] express the award as points at the target.

For example, with 0.04 points per passing yard, 3 points at 300 yards, and 2 more points at 400 yards:

| Passing yards in one week | Base points | Bonus points | Total |
| --- | --- | --- | --- |
| 299 | 11.96 | 0 | 11.96 |
| 300 | 12.00 | 3 | 15.00 |
| 400 | 16.00 | 5 | 21.00 |

Targets can be arbitrary positive finite numbers, and awards can be fractional or negative finite numbers. A supported category with a zero base multiplier can still have active bonuses. A zero-point award has no scoring effect. Numeric support does not imply that every combination is configurable through Yahoo's UI.

### Compound categories award once

Some Yahoo categories combine several source counters. Individual return yards, ID 14, are `kr_yd + pr_yd`; team defense return yards, ID 48, are `def_kr_yd + def_pr_yd`. The scorer sums those components before comparing the threshold.

A 100-yard return bonus applies once to 60 kickoff-return yards plus 40 punt-return yards. It also applies only once to 100 kickoff-return yards plus 120 punt-return yards. Creating a separate threshold for each component would miss the first example and double-count the second.

Linear multipliers for a compound category apply to each component. If distinct mapped categories contribute a multiplier to the same canonical field, the adapter adds the coefficients. The category's bonus remains a single rule.

### Score each actual week before adding weeks

Threshold awards require weekly evidence. A season with two 200-yard passing weeks earns no 300-yard weekly award, even though the season total is 400 yards. The NFL actuals and scoring-leader paths call the same weekly scorer and add the resulting weekly points afterward.

The evaluator uses decimal arithmetic and rounds the completed weekly score once to two decimal places with `ROUND_HALF_UP`. Supported counters missing from a sparse weekly record contribute zero. A record explicitly reporting no games played cannot earn a bonus. Empty records and records containing only unrelated metadata do not establish participation or a relevant statistic.

Yahoo bonuses are not aliases for Sleeper's precomputed range flags. Sleeper's [scoring documentation][sleeper-help] describes yardage bonus ranges that do not stack. Using those flags for Yahoo's cumulative awards would change the result.

## Supported category catalog

Names below are the observed Yahoo catalog names. Context separates identically named categories, such as an interception thrown by a passer, a team defense interception, and an individual defender's interception. `+` means sum the listed counters for a threshold. **Added: Yes** marks the 20 mappings introduced by this change.

The complete ID/name catalog comes from the maintained `yahoofantasy` library's [generated NFL catalog][yahoo-catalog]. Its [generator][yahoo-generator] requests Yahoo's `game/nfl/stat_categories` resource. Selected category IDs were independently checked against public Yahoo player-table column titles and their `sort` IDs. Selected nonzero canonical fields were checked against real public Sleeper weekly payloads. These observations and the separate mapping decisions are retained in the evidence fixture; they are not a claim that every historical record has been compared across providers.

### Participation and offense — 31 categories

| Yahoo ID | Yahoo category | Canonical weekly counters | Added |
| --- | --- | --- | --- |
| 0 | Games Played | `gp` | Yes |
| 1 | Passing Attempts | `pass_att` | — |
| 2 | Completions | `pass_cmp` | — |
| 3 | Incomplete Passes | `pass_inc` | — |
| 4 | Passing Yards | `pass_yd` | — |
| 5 | Passing Touchdowns | `pass_td` | — |
| 6 | Interceptions | `pass_int` | — |
| 7 | Sacks | `pass_sack` | — |
| 8 | Rushing Attempts | `rush_att` | — |
| 9 | Rushing Yards | `rush_yd` | — |
| 10 | Rushing Touchdowns | `rush_td` | — |
| 11 | Receptions | `rec` | — |
| 12 | Receiving Yards | `rec_yd` | — |
| 13 | Receiving Touchdowns | `rec_td` | — |
| 14 | Return Yards | `kr_yd` + `pr_yd` | — |
| 15 | Return Touchdowns | `kr_td` + `pr_td` | — |
| 16 | 2-Point Conversions | `pass_2pt` + `rush_2pt` + `rec_2pt` | — |
| 17 | Fumbles | `fum` | — |
| 18 | Fumbles Lost | `fum_lost` | — |
| 57 | Offensive Fumble Return TD | `fum_rec_td` | — |
| 58 | Pick Sixes Thrown | `pass_int_td` | — |
| 59 | 40+ Yard Completions | `pass_cmp_40p` | Yes |
| 60 | 40+ Yard Passing Touchdowns | `pass_td_40p` | Yes |
| 61 | 40+ Yard Run | `rush_40p` | Yes |
| 62 | 40+ Yard Rushing Touchdowns | `rush_td_40p` | Yes |
| 63 | 40+ Yard Receptions | `rec_40p` | Yes |
| 64 | 40+ Yard Receiving Touchdowns | `rec_td_40p` | Yes |
| 78 | Targets | `rec_tgt` | Yes |
| 79 | Passing 1st Downs | `pass_fd` | Yes |
| 80 | Receiving 1st Downs | `rec_fd` | Yes |
| 81 | Rushing 1st Downs | `rush_fd` | Yes |

The six 40+ yard categories, IDs 59–64, consume actual event-count fields. For example, `pass_cmp_40p` counts qualifying completions. It cannot be reconstructed merely by dividing total passing yards by 40. A threshold on that category measures the number of qualifying events in the week, while its base multiplier scores each event. The same distinction applies to first downs and targets: the source must supply the category's counter.

### Kicking — 15 categories

| Yahoo ID | Yahoo category | Canonical weekly counters | Added |
| --- | --- | --- | --- |
| 19 | Field Goals 0-19 Yards | `fgm_0_19` | — |
| 20 | Field Goals 20-29 Yards | `fgm_20_29` | — |
| 21 | Field Goals 30-39 Yards | `fgm_30_39` | — |
| 22 | Field Goals 40-49 Yards | `fgm_40_49` | — |
| 23 | Field Goals 50+ Yards | `fgm_50p` | — |
| 24 | Field Goals Missed 0-19 Yards | `fgmiss_0_19` | — |
| 25 | Field Goals Missed 20-29 Yards | `fgmiss_20_29` | — |
| 26 | Field Goals Missed 30-39 Yards | `fgmiss_30_39` | — |
| 27 | Field Goals Missed 40-49 Yards | `fgmiss_40_49` | — |
| 28 | Field Goals Missed 50+ Yards | `fgmiss_50p` | — |
| 29 | Point After Attempt Made | `xpm` | — |
| 30 | Point After Attempt Missed | `xpmiss` | — |
| 84 | Field Goals Total Yards | `fgm_yds` | Yes |
| 85 | Field Goals Made | `fgm` | Yes |
| 86 | Field Goals Missed | `fgmiss` | Yes |

Total field-goal yards, ID 84, use `fgm_yds`. They are separate from made-field-goal distance counts and total field goals made. Yahoo's [FAQ][yahoo-help] states that total-yard scoring adds to configured distance-category points; the adapter preserves both configured components.

### Team defense and special teams — 28 categories

| Yahoo ID | Yahoo category | Canonical weekly counters | Added |
| --- | --- | --- | --- |
| 31 | Points Allowed | `pts_allow` | Yes |
| 32 | Sack | `sack` | — |
| 33 | Interception | `int` | — |
| 34 | Fumble Recovery | `fum_rec` | — |
| 35 | Touchdown | `def_td` | — |
| 36 | Safety | `safe` | — |
| 37 | Block Kick | `blk_kick` | — |
| 48 | Return Yards | `def_kr_yd` + `def_pr_yd` | Yes |
| 49 | Kickoff and Punt Return Touchdowns | `def_st_td` | — |
| 50 | Points Allowed 0 points | `pts_allow_0` | — |
| 51 | Points Allowed 1-6 points | `pts_allow_1_6` | — |
| 52 | Points Allowed 7-13 points | `pts_allow_7_13` | — |
| 53 | Points Allowed 14-20 points | `pts_allow_14_20` | — |
| 54 | Points Allowed 21-27 points | `pts_allow_21_27` | — |
| 55 | Points Allowed 28-34 points | `pts_allow_28_34` | — |
| 56 | Points Allowed 35+ points | `pts_allow_35p` | — |
| 67 | 4th Down Stops | `def_4_and_stop` | Yes |
| 68 | Tackles for Loss | `tkl_loss` | Yes |
| 69 | Defensive Yards Allowed | `yds_allow` | Yes |
| 70 | Defensive Yards Allowed - Negative | `yds_allow_negative` | — |
| 71 | Defensive Yards Allowed 0-99 | `yds_allow_0_100` | — |
| 72 | Defensive Yards Allowed 100-199 | `yds_allow_100_199` | — |
| 73 | Defensive Yards Allowed 200-299 | `yds_allow_200_299` | — |
| 74 | Defensive Yards Allowed 300-399 | `yds_allow_300_349` + `yds_allow_350_399` | — |
| 75 | Defensive Yards Allowed 400-499 | `yds_allow_400_449` + `yds_allow_450_499` | — |
| 76 | Defensive Yards Allowed 500+ | `yds_allow_500_549` + `yds_allow_550p` | — |
| 77 | Three and Outs Forced | `def_3_and_out` | Yes |
| 82 | Extra Point Returned | `def_2pt` | — |

The Yahoo adapter normalizes the two lowest defensive-yardage flags from observed `yds_allow`: negative yards are `< 0`; ID 71 is `0 <= yards < 100`. The canonical field name `yds_allow_0_100` is retained internally, but **100 belongs to Yahoo's 100–199 category**, not its 0–99 category. IDs 74–76 combine narrower, mutually exclusive source bands. Those band flags describe category values and are distinct from additional threshold bonuses.

ID 82 is the **team defense** extra-point-return category. It does not provide evidence for an individual player's corresponding Yahoo category, ID 83.

## Unsupported categories and explicit failures

These 13 catalog categories do not have admitted mappings:

| Yahoo ID | Yahoo category |
| --- | --- |
| 38 | Tackle Solo |
| 39 | Tackle Assist |
| 40 | Sack |
| 41 | Interception |
| 42 | Fumble Force |
| 43 | Fumble Recovery |
| 44 | Defensive Touchdown |
| 45 | Safety |
| 46 | Pass Defended |
| 47 | Block Kick |
| 65 | Tackles for Loss |
| 66 | Turnover Return Yards |
| 83 | Extra Point Returned |

### Why individual defense needs more evidence

The presence of a similarly named Sleeper counter is insufficient to establish Yahoo scoring parity. Individual defense requires both event semantics and position applicability. The current neutral bonus model carries stat components, target, and points; it does not carry Yahoo's `stat_position_types` or the player's provider-specific `position_type`.

Public 2022 week 18 comparisons in the evidence fixture show that, for the sampled defensive players, Yahoo solo tackles include both Sleeper `idp_tkl_solo` and `st_tkl_solo`. That observation does not establish whether Yahoo awards the same IDP category to an offensive player who makes a special-teams tackle. A global sum without that scope could credit ineligible players.

Overlap also differs by statistic. The public Sleeper observations include special-teams forced fumbles already counted in `idp_ff`; adding `st_ff` would count those events twice. Other records contain `st_fum_rec` without `idp_fum_rec`. A universal rule to add defensive and special-teams fields is therefore unsupported. The evidence also includes provider stat-correction differences, which reinforce the need to preserve Yahoo's recorded totals.

For ID 83, no individual source counter was verified. The observed team counter `def_2pt` cannot identify the player who returned the attempt. Do not invent an `idp_2pt` alias or substitute a team statistic for an individual statistic.

To admit an IDP mapping, preserve or otherwise verify category/player applicability, establish any overlap with special-teams counters, and compare actual weekly Yahoo values with the proposed source computation. Threshold support then follows from the same generic model; adding another list of milestone amounts would not resolve missing event or eligibility evidence.

### Parsing and validation behavior

The adapter accepts a bonus record with exactly `target` and `points`. It can normalize a singleton, a list, a `bonus` wrapper, a numeric-key collection with an optional `count`, and a fragmented target/points record. An advertised count must equal the number of parsed records. `None`, `[]`, and `{}` represent empty bonus collections.

The [`YFPY` bonus model][yfpy-bonus] documents the parsed `target` and `points` fields. The wrapper variants exercised in [the parser tests](../tests/test_yahoo_scoring.py) are **synthetic robustness fixtures**, not authenticated captures proving that Yahoo emits every variant. No verified `from`/`to` interval bonus schema was found, and the parser does not infer interval rules from unfamiliar fields.

The adapter raises an actionable `YahooDataError` for:

- An active category without a verified mapping, including a category whose base value is zero but whose bonus is nonzero. The error includes the Yahoo stat ID, category name when supplied, base value, and active bonus count.
- Missing target or points, unknown bonus keys or envelopes, or a collection count inconsistent with its records.
- Invalid, boolean, nonnumeric, or nonfinite values; invalid stat IDs; negative targets; duplicate source stat records; or repeated active targets within one category.
- An active zero-target Yahoo bonus. At zero, a missing counter could appear to qualify every player, so the source must establish applicability before this rule can be supported.
- An import that produces no mapped scoring settings.

Unknown categories with a zero base multiplier and no active bonus can be ignored after validating their input. Unknown or malformed active rules are never silently dropped.

The neutral scorer has an additional zero-target defense for other callers: even a played week requires an observed component of the rule. `gp = 1` alone does not prove that a kicker-only rule applies to a receiver. This protection does not make zero-target Yahoo imports supported; the Yahoo adapter rejects them earlier.

### Other boundaries

This work does not establish complete support for Yahoo's fractional-yardage and negative-yardage toggles. Yahoo's [FAQ][yahoo-help] limits those toggles to yardage categories. Accepting fractional multipliers or negative bonus awards, and rounding the result with decimals, is a different capability from reproducing every whole-yard or negative-yard configuration.

Likewise, season aggregates cannot reveal the number of long plays or weekly threshold crossings. Categories without a verified underlying event counter or an independently justified derivation remain unsupported. Sparse records are not proof that an unavailable category has a true zero value.

## Authoritative results and derived analysis

Yahoo's league-context `player_points`, team scores, and matchup results remain authoritative. The [Yahoo API documentation][yahoo-api] distinguishes player statistics in league context, where fantasy points are included. The adapter imports those points directly and does not add parsed bonuses to them again.

Canonical weekly counters support derived NFL production and scoring-leader calculations. Yahoo's `get_stats` path obtains Sleeper's raw NFL statistics and applies Yahoo-specific normalizations before those calculations. A correct mapping does not eliminate provider stat corrections or all underlying data differences. Derived calculations must not overwrite Yahoo's official lineup totals or matchup outcomes.

The scoring model is deliberately propagated to every derived actuals path. An integration test adds a synthetic bonus to the Yahoo import fixture and checks that recorded Yahoo player points remain unchanged, while the normalized league retains the new bonus separately.

### Projection and rookie-comparison gates

A projected weekly average does not provide a probability of reaching a milestone. A season points projection provides even less information about which weeks reach one. The application therefore omits comparisons it cannot price correctly:

| Consumer | Behavior when an active threshold bonus exists |
| --- | --- |
| Draft production projection baseline | Does not use published standard/PPR season points as a comparable league projection. |
| Analyst recap projection comparisons | Omits projection-based bust labels; retains verified results. |
| Analyst upcoming-week outlook | Returns no projected outlook before fetching projections. |
| CLI simulation and Analyst command | Declines simulations whose projections omit bonuses; the Analyst command retains actual results while omitting projection-based busts and the projected outlook. |
| Historical offensive rookie cohorts | Omits cohorts if any bonus can reach the offensive rookie population. Bonuses exclusively on recognized kicker/team-defense counters do not by themselves disable those cohorts. |

Existing rookie component-coverage checks still apply independently. A zero-point rule does not trigger these bonus gates. These limits concern projection-dependent analysis; actual weekly scoring and provider-recorded results continue to work.

## Persistence and cache behavior

`League.scoring_bonuses` defaults to an empty list. Serialization preserves each rule's stat keys, target, and points; loading an older league without that field preserves its original linear scoring behavior.

Raw weekly statistics are cached by **normalized provider namespace**, season, and week:

```text
nfl_stats_{source_namespace}_{season}_{week}.json
```

For example, Yahoo-normalized and Sleeper-normalized stats have separate files because their defensive-yardage boundary conventions differ. Old unnamespaced raw files are not reused: their originating provider cannot be proved. Within one namespace, leagues may share raw statistics, but each league applies its own multipliers and bonuses after reading the cache. Derived bonus flags or league-specific point totals are not written into that shared raw record. Live weeks are not persisted as completed historical snapshots.

There is **no global `ChainCache` schema-version bump** for this change. Before this fix, the Yahoo adapter rejected active bonus rules, so a successfully imported pre-change Yahoo cache cannot be a bonus league whose rules were silently omitted by that importer. Successfully cached leagues without the new field can safely default to no bonuses. A failed bonus import needs an explicit retry after deployment; invalidating every successful league cache would not repair that failed job.

## Retrying a failed free data refresh

After correcting a scoring-mapping failure, an administrator can resume the existing stopped data-refresh job. The recovery applies specifically to `refresh` or `analyst_refresh` operations in `needs_attention` with reason `execution_failed`. A repeated member refresh request joins the stopped operation; it does not automatically replay a permanent failure.

The [administrative command](../api/app/services/generation/administration.py) checks the expected state and worker generation before requeueing. It preserves the same operation ID, original actor, active key, and idempotency records; clears stale progress; records the administrator's reason; and lets the next worker claim receive a fresh generation. Batch recovery uses the same command contract after validating its preview.

Retry rechecks the saved actor and league membership. For a Yahoo league, the original actor's connection must remain connected and the league grant must match both the current connection generation and the generation stored on the job. An administrator's own access cannot substitute for the original actor's access. The administrative endpoint retains its existing admin authorization.

A free refresh has no AI request allowance to renew. Recovery requires `calls == 0`, `max_calls == 0`, and no `ProviderAttempt` receipt. A job with any such paid-provider activity is rejected with `data_refresh_has_provider_activity`. The retry does not require a new AI budget or create paid-provider receipts. Data-provider reads performed during refresh remain part of the free collection path.

Paid generation keeps its existing authorization, allowance, budget, unresolved-provider-outcome, and receipt-reconciliation guards. The new recovery path cannot reclassify a paid operation as free or authorize an additional paid attempt. [Recovery tests](../api/tests/test_generation_refresh_recovery.py) exercise a failed refresh, explicit same-job retry, successful worker completion without a paid send, stale action rejection, removed membership, changed Yahoo connection generation, and rejection of existing provider activity.

## Evidence and verification

The [provenance fixture](../tests/fixtures/yahoo/scoring_category_evidence.json) contains 87 observed Yahoo ID/name entries, 35 selected nonzero Sleeper counter observations, and eight cross-provider solo-tackle comparisons. Public NFL player/team IDs identify the source records. Mapping decisions are stored separately from observations, and the fixture explicitly records unsupported cases and overlap limitations. It contains no private account or league payload.

The catalog is a maintained provider library's generated snapshot, with selected IDs checked on Yahoo's public pages. An anonymous request to Yahoo's game stat-category resource returned HTTP 401; this evidence must not be described as a fresh authenticated capture of the current NFL game resource. Source URLs and retrieval metadata are stored in the fixture.

The following tests cover the implementation contract; numerical parser examples are synthetic unless explicitly identified as public observations:

- [Yahoo parser tests](../tests/test_yahoo_scoring.py): arbitrary targets, inclusive boundaries, cumulative awards, compound single awards, zero-base categories, known event counters, wrapper handling, explicit rejection, and unchanged Yahoo recorded points.
- [Weekly scorer tests](../tests/test_threshold_scoring.py): weekly-before-season aggregation, decimal arithmetic, negative awards, participation/placeholder handling, position reception premiums, and model serialization.
- [NFL points fetch tests](../api/tests/test_nfl_points_fetch.py): league-specific scoring after raw-cache reads, provider namespace isolation, live-week handling, and authoritative matchup preservation.
- Projection, rookie-cohort, scoring-leader, and recovery tests verify that consumers use the new model or omit an unsupported comparison as described above.

### External sources

- [Yahoo Fantasy Sports API documentation][yahoo-api]: league-context points and game stat-category resources.
- [Yahoo scoring categories and plays FAQ][yahoo-help]: cumulative bonuses, yardage toggles, and total field-goal yards.
- [Public Yahoo league settings][yahoo-settings] and [additional return-yard settings][yahoo-return-settings]: displayed targets and category configuration.
- [Generated NFL category catalog][yahoo-catalog] and [its API generator][yahoo-generator]: complete researched ID/name list.
- [YFPY parsed Bonus model][yfpy-bonus]: `target` and `points` fields.
- [Sleeper scoring options][sleeper-help]: event categories and nonstacking yardage bonus ranges.
- [Sleeper 2025 week 1 raw stats][sleeper-w1], [2025 week 4 raw stats][sleeper-w4], and [2022 week 18 raw stats][sleeper-idp]: actual counter observations.
- [Public Yahoo 2022 week 18 IDP results][yahoo-idp]: cross-provider tackle comparisons; additional page URLs are in the fixture.

[yahoo-api]: https://sports.yahoo.com/developer/docs/
[yahoo-help]: https://ca.help.yahoo.com/kb/fantasy-football/scoring-categories-plays-faq-fantasy-football-sln6442.html
[yahoo-settings]: https://football.fantasysports.yahoo.com/f1/viewsettings/2026/722724
[yahoo-return-settings]: https://football.fantasysports.yahoo.com/2020/f1/602442/settings
[yahoo-catalog]: https://raw.githubusercontent.com/mattdodge/yahoofantasy/master/yahoofantasy/stats/nfl.py
[yahoo-generator]: https://raw.githubusercontent.com/mattdodge/yahoofantasy/master/yahoofantasy/stats/generate.py
[yfpy-bonus]: https://yfpy.uberfastman.com/models/#bonus
[sleeper-help]: https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available
[sleeper-w1]: https://api.sleeper.app/v1/stats/nfl/regular/2025/1
[sleeper-w4]: https://api.sleeper.app/v1/stats/nfl/regular/2025/4
[sleeper-idp]: https://api.sleeper.app/v1/stats/nfl/regular/2022/18
[yahoo-idp]: https://football.fantasysports.yahoo.com/2022/f1/90001/players?pos=D&stat1=S_W_18&status=ALL&sort=38&count=25
