# Dynasty Bitch recap pilot implementation plan

**Goal:** Build one local, reviewable 90-second episode before paying to repeat it.

**Architecture:** An offline episode package contains the approved script, three screenshot-sourced facts, a deterministic graphics timeline, and a separate credit ledger. A local browser player previews and exports the episode. Higgsfield narration is a manual, quoted operation; this package never calls a provider or schedules work. Real league IDs live only in ignored local configuration.

**Tech stack:** Python standard library, browser Canvas/MediaRecorder, existing Playwright for verification. Existing app typography and colors. No new runtime dependency.

**Approved brief:** Dynasty Bitch only; Cal Mercer, original former player and seasoned deadpan reporter; 90 seconds; dark humor, natural profanity and fictional substance-use history. Keep Reid as the baseline while the user decides whether to wait for Boston. The approved pitcher/bartender/coach line is the character reference. Football claims use the supplied Week 4 screenshot. Narration and media remain explicitly pending until a voice is selected and audio exists.

## Constraints and review focus

- One league, one episode. No scheduler, automatic paid requests, or public publication.
- No real external IDs in committed content; copy identity from the selected local cache into ignored output.
- Keep quotes distinct from reported charges. Missing charges are unknown, including failed requests.
- Reserve before a manual provider attempt; duplicate/unresolved attempts block another reservation. Credits require an explicit finite cap.
- Bind attempts and audio to the script fingerprint. Never imply a revised script has a matching old take.
- Browser playback needs no paid service. Export without audio is visibly marked a graphics preview.
- Transcript always available; keyboard controls, seek/replay, mobile layout, reduced motion, useful media errors.

## Implementation

- [x] Add failing tests for league scope, quote vs actual cost, unresolved attempts, duplicate reservations, script/audio fingerprint and timeline coverage.
- [x] Build the small local package/ledger CLI and author the 90-second script and timed graphics.
- [x] Build the browser preview/export controls using local assets. Verify desktop/mobile, timeline boundaries, play/pause/seek and failed audio.
- [x] Replace reader-facing Analyst/roast invitation labels with Weekly recap and Read the Week N recap. Preserve archive routes and saved editions.
- [x] Run focused tests, web suite/lint/typecheck, browser checks and one review; commit with the required skill gate.

## Execution notes

The local cache identifies Dynasty Bitch but has no current recap. The supplied screenshot is the source for the pilot's three factual claims; this is a local editorial draft, not a newly verified published edition. Voice ID and paid credit cap remain unselected. Build all independent work now; never substitute another voice or start an unquoted paid take.


## Verification

- 1,086 Python tests passed, including eleven pilot scope/ledger/audio-binding checks.
- 896 web tests passed; Next lint, TypeScript checking and production build passed.
- Python Ruff check and format passed; player JavaScript lint passed.
- Browser playback, seeking, keyboard controls, reduced motion and 1440/768/390/320px layouts checked.
- Four browser checks passed, including three regressions reproduced and fixed audio-tail seeking, encoder-error partial downloads, and background cancellation track cleanup.
- League-scope mutation was rejected by its named test; original implementation restored byte-for-byte.
- Finish review: ship after the two material media findings were resolved.
- No provider generation submitted, no quoted narration, no deployment. Voice selection, narration charge receipt and final speech/caption alignment remain pending.

- Added byte-range serving to the local preview so imported media can seek before the whole file has buffered. The standard static Python server does not support those requests.
- Final graphics-only export decoded at 1280×720, 89.977 seconds.
