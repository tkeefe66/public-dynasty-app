Use the claim evidence index alongside the original facts. It reorganizes saved
evidence; it does not authorize new claims or replace factual review. Keep its
source IDs backstage, never in the published recap.

For each single-swap claim, match the owner AND the benched player AND the
started player in one single_swaps row. A matching position or slot alone does
not identify a swap. All gain, team score, opponent score, signed margin and
result values must come from that SAME source_id. Never borrow another owner's
matchup_effect or confuse points_gained with the resulting victory margin.
In review findings about a swap, cite its source_id, owner and player pair in
evidence so the correction can check the same row. Correct rounding is valid:
a margin of 28.96 can be called a 29-point win. Rounding cannot change the
winner, a tie, rank, or the meaning of the underlying quantity.

For report chronology, use player_news_timing and the named player's own NFL
kickoff in player_context. The fantasy matchup start, Sunday slate, another
player's kickoff, observed_at and evidence cutoff are not substitutes. An
article published after that player's Thursday kickoff cannot establish what
the manager knew before starting him, even if the fantasy matchup lists Sunday.
An after/at report cannot justify pregame blame. Before means only publication
preceded kickoff; the report must still explicitly concern the relevant game.
Unknown means timing is unproven. Publication time is not injury/event time.

Check units as well as numbers: player points and points_gained are fantasy
points, not receiving/rushing yards or receptions. NFL yards and catches need
their own explicit news/stat evidence. A supported number with the wrong unit
is needs_correction; evidence identifying an actual error cannot be marked
supported. Correct every repetition of a verified error, then review the whole
result. An unresolved error still requires approved=false.
