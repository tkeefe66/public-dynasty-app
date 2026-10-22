# Editorial recovery of a saved video script

An exhausted script attempt may be corrected without buying another draft. The
paid operation and all provider receipts remain unchanged. Recovery creates a
separate zero-call operation and an `editorial_reviewed` artifact; it never
claims that the provider approved the edited text.

In Admin → AI writing → Weekly recap, select the affected episode and choose
**Edit saved script**. Review the saved article and failed review findings, edit
the narration and source-number references, and complete each factual review
check after the final edit. **Prepare free preview** validates the exact script
and shows the maximum narration cost. It makes no provider request and reserves
no money. **Approve corrected script** binds the approval to that preview and
reserves narration under the existing episode, monthly, and application limits.
Changing content invalidates the preview and review checkboxes.

The backend independently rechecks the administrator, league access, current
article and facts, original settled receipts, current voice verification,
execution epoch, policy, budget and absence of existing media. Both preview
and approval have durable audit records. Approval is idempotent and must not
create a second artifact or narration reservation on replay.

For an operator-assisted recovery, `recap_video.editorial.preview_editorial`
accepts the corrected structured script and an explicit independent semantic
review. The review identifies its actual reviewer and kind, binds the exact
script and article digests, checks every segment and all review categories, and
contains no unresolved issues. Browser requests derive the reviewer from the
authenticated administrator; they cannot submit a different reviewer identity.
Delegated AI review is recorded as such, not as human or provider review.

`apply_editorial` requires the exact preview identifier and digest. Media stages
validate the durable editorial authority in addition to the ordinary source,
permission, budget, speech and media checks. Editing an artifact, source,
receipt or approval after selection does not silently gain authority.

Script approval does not publish the video or expand sharing. A corrected
edition still requires explicit finished-media publication approval. Member-only
publication does not create a public share link. Existing failed operations and
their charges remain available for diagnosis and accounting.
