# Yahoo account connection and Add League

User request: build Yahoo league addition alongside the existing Sleeper page.
Prior authorization: read-only Yahoo consent, first league selected, keeper format.

## Design

Keep Google as the app identity. Yahoo is a linked data source, not a second login.
The Add League page offers Sleeper and Yahoo. Yahoo opens a read-only OAuth consent
and returns to the same page to list the user's NFL leagues. Adding verifies the
league against Yahoo before creating membership; existing leagues have Open links.

API owns OAuth exchanges, encrypted tokens and renewal. Web owns the browser-bound
state cookie and exact registered callback. Start and disconnect require same-origin
POST/DELETE. Callback requires the original app session, matching cookie, and a
single-use, expiring database state bound to that user and an encrypted PKCE verifier.
No provider tokens enter browser JavaScript or application responses.

Add separate connection/state/grant tables. AES-256-GCM binds ciphertext to user,
provider, purpose and version. PostgreSQL row locks serialize token rotation and
disconnect across replicas. API credentials come from runtime configuration. Missing
configuration yields an explicit unavailable state, with Sleeper still usable.

Each verified league grant belongs to a connection generation. Reconnecting clears
grants, not saved memberships or analysis; discovery revalidates membership access.
Yahoo league reads require a current grant and connection, revalidated against
Yahoo at least every five minutes; social-card anonymous
access and the Sleeper admin/allowlist bridge do not expose Yahoo private data.
Manual and scheduled refresh use the same per-user credential resolver. Scheduled
refresh can use any still-connected, verified league member.

The existing Yahoo adapter remains the normalization layer. Its conservative owner
identity handling and keeper grading remain intact. Owner continuity across seasons
is not inferred from names or team numbers.

## Implementation sequence

1. Add adversarial tests for token encryption, state replay/expiry/user binding,
   refresh rotation, discovery, forbidden imports and disconnect.
2. Add additive migration, connection service, user-scoped API routes and scoped
   manual/scheduled refresh. Close generic membership and social-card bypasses.
3. Add same-origin OAuth start/callback routes, provider selector and Yahoo results.
   Test error/cancel/reconnect, imported links, and Sleeper regressions.
4. Run API/engine/frontend suites, lint, types and build. Review new authentication
   boundaries and correct findings. Document deployment variables and callback.
5. Commit the reviewed implementation. Deploy only after confirming Railway API
   and Web as the target. Verify the actual browser connection/import when available.

## Verification boundaries

Mocked OAuth tests prove application behavior, not Yahoo availability. Captured
anonymized Yahoo payloads cover discovery shape. Production readiness also requires
runtime client id, exact HTTPS callback, encryption key and database migration.
Never commit actual account/league identifiers or tokens. Never install a global
developer token as production credentials.

## Implementation evidence

Implemented 2026-09-27. Full engine suite: 1017 passing; frontend: 845 passing.
API suite including the final HTTP lifecycle regression: 848 passing. The HTTP
test exercises real JWT authentication, connect, discovery, verified add, private
read, cross-user denial and disconnect. Standalone typecheck, frontend lint,
production build and new-module Ruff checks pass. Existing suite warnings remain.

SQLite migration upgrade through 0008 and backup/restore of encrypted connection,
pending-state and grant rows pass. PostgreSQL lock behavior was source-reviewed;
no local PostgreSQL server was available for concurrent integration tests.

Browser checks at 1440px and 390px verify Yahoo connect, synthetic league results,
no horizontal overflow, and preserved Sleeper search. OAuth provider exchanges in
these tests are simulated. The original development importer used real Yahoo data.

Two independent security reviewers found and verified fixes for permanent grants,
unlimited repeated add discovery, and encoded/control-character proxy paths. Denied
membership reconciliation is committed so request rollback cannot restore stale
grants. Removing the grant-expiry check was confirmed to fail the named regression;
the original source was restored byte-for-byte.

Deployment target verified via Railway status: existing production API and Web.
Runtime Yahoo settings are not configured yet. Target confirmation was requested
before publication; no production mutation has been performed in this phase.
