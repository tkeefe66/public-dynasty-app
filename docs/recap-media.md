# Shareable recap episodes

A selected episode attaches to one published recap revision. The existing
`/share/analyst/<token>` page shows video, captions, MP4/MP3 downloads and article.
The poster supplies Open Graph/message-preview metadata; real recipient rendering
requires separate device evidence.

The [weekly operations runbook](recap-video-operations.md) is the authoritative
workflow: Tuesday readiness → managed article → reviewed narration script →
restricted worker → speech/render QA → finished-preview approval → public selection.
It includes exact routes/configuration, cap enforcement, service lifecycle,
migrations, private storage, backup/restore, local acceptance and release gates.

## Publication and migration

New publication requires an existing checked media stage and persisted scoped
admin approval. `python -m app.publish_recap_media --help` documents the current
stage/approval CLI; an arbitrary four-file folder is not publication authority.
Use authenticated Admin → AI writing episode controls to review a finished preview.
Member article sharing does not grant media approval or standing future consent.

Existing legacy bundles and tokens migrate byte-identically through the dry-run
reconciliation command in the runbook. Keep the explicit legacy serving mode until
reconciliation is reviewed. After database activation, missing authority, outage,
withdrawal or restore quarantine never falls back to stale filesystem content.
Do not use the old folder-copy workflow to create new unchecked publication.

## Storage and reader behavior

New immutable media lives in API-owned private storage. Worker access is limited
to leased assets; the worker has no bucket, database or publication credentials.
Only `video.mp4`, `audio.mp3`, `poster.jpg` and `captions.vtt` are public derivatives.
Every GET/HEAD/range checks current token, revision and publication authority.
Next streams bytes without buffering and preserves seeking metadata. Scripts,
facts, transcripts, raw receipts and diagnostics stay private.

Corrections withdraw stale content; share revocation blocks subsequent requests.
Explicit restore rotates the token and retains the old tombstone. Neither action
can recall downloaded bytes, buffered playback or cached recipient previews.
Revocation is not deletion consent. Retention and backup pins remain governed by
the runbook, with manual offline verification before backup pins can be retired.

This is a gated implementation. Local synthetic tests grant no production voice,
physical-phone, message-preview or Railway runtime qualification. No automatic
paid activation follows from running the acceptance suite.
