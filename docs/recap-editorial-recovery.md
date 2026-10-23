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

Preview also validates the video scene plan before approval. If an older
editorial approval failed before any media stage or request existed, an operator
may retire that unused approval with `retract_unused_editorial`. The original
artifact and audit remain immutable, its unused narration reservation is
released, and a new reviewed revision can be approved. Once media work starts,
this path refuses retirement so paid work cannot be silently discarded.

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

If narration succeeded but storage failed, recover the exact retained provider
history item before considering another request. History downloads can add ID3
provenance metadata and alter the encoder tag terminator. Recovery restores only
bounded metadata variants and accepts a recording only when its complete bytes
match the original saved SHA-256 and size. MPEG audio is never rewritten. A
different recording remains blocked. Partial recovery preserves untouched later
chunks and requires independent speech and media validation before publication.

Older workers may upload the history download before normalizing its metadata.
The API independently verifies the stored bytes, request identity, stage and
generation before restoring the original hash. It retains both the downloaded
receipt and normalized receipt in the audit trail; replaying the same recovery
does not create another asset or change the original charge.

After repairing the underlying cause, the Weekly recap failure breaker can be
reset through the existing administrator control. Reset does not retry failed
jobs, change receipts, clear other holds, or alter approved spending limits.

## Pronunciation corrections

An operator can use `preview_pronunciation` to prepare a narration-only correction
for an accepted editorial script. The preview keeps the script and voice intact,
binds the exact pronunciation dictionary version and rules, and prices the
replacement requests against existing limits. Preparing it makes no provider
request. This operator path is not yet exposed as a browser form.

Before `approve_pronunciation`, retain the dictionary readback, an actual sample
request and recording, and the administrator's listening review. A pronunciation
spelling or a passing transcript is not listening evidence. Additional paid
requests need explicit approval; the preview does not grant it. Approval creates
a new media execution using the same script, preserves prior receipts and
charges, and leaves independent speech and media checks in place. It neither
rewrites the article nor grants recurring publication authority.

Finished editorial or recovered media uses an exact member-only publication
review binding. Approval records factual and playback review; selection rechecks
the same stages, assets, source, receipts and costs. This does not fabricate a
phone review or grant public sharing or automatic-publication qualification.

When a person has listened to the finished recordings and confirmed flagged
passages, the operator-only `listening.approve_listening` path can adjudicate
spelling differences and low recognizer confidence. It binds the exact audio,
raw transcript, script, stage generation, reviewer and listening evidence.
Original recognition results, timestamps and confidence scores remain intact.
Only explicit bounded word-span corrections are used for caption alignment;
score, result, negation and malformed-evidence failures cannot be waived.
Rendering and publication recheck the saved review. This makes no provider call
and does not grant public sharing or automatic publication authority.

`pronunciation.renew_finished_preflight` can bind a fresh free preflight to
already completed narration after a verification-code release. It requires the
same voice, account, settings and rate, and preserves the original approval.
It cannot renew an unfinished paid checkpoint or authorize a new narration.
