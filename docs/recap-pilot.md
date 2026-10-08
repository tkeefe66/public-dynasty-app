# Dynasty Bitch video pilot

This is a local, single-episode experiment for 2026 Week 4. It does not enable video generation in the deployed app. The browser renders graphics locally; narration is the only intended Higgsfield generation. No provider request is made by these scripts, by opening the preview, or by exporting video.

The current draft uses the three facts supplied in the screenshot: Mikey scored 189.2, Parker beat Keegan by 55.1, and Mikey received 95.3 points from trade-acquired starters. The 50.4% graphic is derived from 95.3 / 189.2. The source note identifies this as screenshot-sourced, not newly verified against the live API.

## Cal Mercer

Original fictional former football player and beat reporter. Talented, charismatic and once a crowd favorite; partying and self-sabotage derailed his career. He understands football, sees other people's bad decisions immediately, and tells on himself without recognizing how bad he sounds. His own fictional history can include drinking, drugs, failed comebacks and excuses. Do not imply real owners have those histories.

Seasoned, restrained, deadpan delivery. Let the audience find the punchline. Natural profanity, specific scenes, no laugh after his own jokes. Reid is the candidate the user liked; a restrained Boston accent is still under consideration. A voice name is not a selected provider voice ID. Use the exact selected ID/type from the voice picker.

Approved reference:

> Mikey got 95.3 points from guys he traded for. Identified a problem, made some changes. Personally, I’d order another pitcher and explain to the bartender why it was the coach’s fucking fault.

Write the football observation first. His personal admission must logically connect to that observation. One strong personal story is enough for the pilot; do not force substance-use references into every statistic. Named athlete references are broad character inspiration, not biographical claims or voice imitation targets.

## Local workflow

From the repository root, select the local Dynasty Bitch chain cache using a shell variable. Real IDs belong in that path/configuration, never committed source. Initialization refuses other league names or seasons and refuses an existing output directory.

```sh
python3 scripts/recap_pilot.py init --cache "$PILOT_CHAIN_CACHE"
python3 scripts/recap_pilot.py build
python3 scripts/recap_pilot.py serve --port 4821
```

Open `http://127.0.0.1:4821`. The ignored `.recap-pilot/` folder holds the private configuration, episode, script, receipts and generated assets. Only serve its `preview` subfolder. `episode.json` holds editable narration and scene timings; rebuilding updates `narration.txt` and the preview. The initial package has no narration and labels both playback and export as graphics previews.

Review the script before audio generation. Request one Higgsfield quote for the exact script/model/selected voice. Record the returned price using `quote`; agree an explicit total credit cap before reserving a request. These commands record operator decisions; they do not enforce spending inside the external Higgsfield UI.

```sh
python3 scripts/recap_pilot.py quote --credits "$QUOTED_CREDITS" --model "$AUDIO_MODEL" --voice-id "$VOICE_ID" --voice-type preset
python3 scripts/recap_pilot.py reserve --attempt take-1 --credit-cap "$APPROVED_PILOT_CAP"
```

Submit that request once through the connected provider. Preserve its returned job ID immediately. On a timeout or ambiguous submission, reconcile the same job instead of starting again. Record submitted/failed/completed status, and record actual credits only when a receipt reports them. Omit `--actual-credits` when unknown; a failed job is not assumed free. Quote and reported charges remain separate. A settled receipt is not overwritten.

```sh
python3 scripts/recap_pilot.py settle --attempt take-1 --status submitted --job-id "$JOB_ID"
python3 scripts/recap_pilot.py settle --attempt take-1 --status completed --actual-credits "$CHARGED_CREDITS" --job-id "$JOB_ID"
python3 scripts/recap_pilot.py costs
python3 scripts/recap_pilot.py audio --file "$NARRATION_FILE" --attempt take-1
python3 scripts/recap_pilot.py build
```

Audio attaches only to a completed attempt for the exact script fingerprint. Editing narration invalidates prior quotes and imported audio. The browser checks the audio file decodes and runs 75–90 seconds; it never speeds up or cuts speech to fit. Check and adjust the chapter boundaries against the actual take before calling it a finished episode. Captions currently divide each scene by word count, so they are draft timing, not forced alignment.

**Export:** Chrome records the local canvas plus attached narration to WebM, at 1280×720 / 30 fps, over 90 seconds. Keep the tab visible; backgrounding stops the export instead of silently producing an incomplete video. Download the resulting file. Without narration the exported video carries a persistent graphics-preview label. No AI-generated footage or presenter is used.

## Before any wider release

Finish the selected voice take and inspect audio/caption synchronization; record the provider receipt and total cost; review the resulting episode. Publishing it in the app, storing finished media in production, and enabling another episode are separate work. The existing recap card still opens the written weekly recap, so its CTA says “Read the Week 4 recap.” Its page and sharing labels use “Weekly recap.”


## Verification commands

```sh
.venv/bin/pytest tests/test_recap_pilot.py -q
node scripts/recap-pilot/test-player.cjs
```

The browser regressions use the running local preview and synthetic audio; they never call Higgsfield. `PILOT_CHROME_PATH` selects an installed Chrome executable and `PILOT_PREVIEW_URL` overrides the local preview URL. Known provider charges remain zero in the initial package because no attempts have been submitted.
