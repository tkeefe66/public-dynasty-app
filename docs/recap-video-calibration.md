# Production narration calibration

This is a private, synthetic delivery test, not league news. It verifies the
already approved Cal Mercer / The Gruff New Yorker voice across two consecutive
requests using `eleven_v4`. It does not change the selected voice.

## Request limits

- Exactly two sequential requests, one take each, no automatic retries.
- Send only the two texts below to ElevenLabs, with the approved voice from
  protected configuration, explicit `eleven_v4`, empty dialogue settings and
  MP3 44.1 kHz / 128 kbps output with timestamps.
- Total submitted text must stay below 3,000 characters. The published API
  rate is $0.08 per 1,000 characters; reserve a maximum of $0.30 for both calls.
- Persist request identity and audio before interpreting the result. An
  uncertain response stops the sequence and requires receipt recovery.
- Keep output private. Review voice consistency, spoken numbers, independent
  transcription, chunk seam, full rendering and playback before qualification.
- This test grants no credit toward the three reviewed weekly episodes.

## First request

This is a production voice check with fictional teams and fictional scores.
Welcome back. I'm Cal Mercer, and apparently the waiver wire was closed for
repairs, because half these lineups look like they were assembled during a
fire drill. Alpha beat Bravo, one hundred twenty-three point four to one
hundred ten point two. Alpha won. Bravo lost. That is a thirteen point two
point margin, not a tie, and not a moral victory. Charlie finished with
ninety-eight points. Delta finished with one hundred two. Delta won by four.
The score is the score, even when your group chat has a six-paragraph theory
about why it shouldn't count. These are test results, not results from your
league. Nobody here is injured, eliminated, or promised a playoff spot. Now,
before we get to the next matchup, remember this: a projection is a forecast.
It is not a final score. You still have to play the games.

## Second request

And that brings us to next week's fictional preview. Echo faces Foxtrot.
Neither team has won that matchup yet. Golf has a bye in this test schedule;
Hotel does not. There are twelve teams in our example, six matchups in a
normal week, and no missing owners hidden behind the phrase everybody else.
We cover the whole league. If a fact changes, the video should stop and be
reviewed before it reaches anyone. If a request fails, save what came back
and check the receipt. Do not order another take just because the first one
is taking its sweet time. The voice should sound like the same person you
heard a moment ago: dry, clear, and mildly disappointed in your bench
management. No dramatic personality transplant halfway through a sentence.
That's the test. Check the numbers, check the names, check that the ending
actually plays, and keep this recording private. I'm Cal Mercer. Set your
lineups, and for the love of football, look at the injury report.

## Evidence

Pricing source checked October 14, 2026:
https://elevenlabs.io/pricing/api (v4, $0.08 per 1,000 characters, before taxes).
Actual account/voice access and model support passed the worker's free preflight.
Paid calibration has not been dispatched.
