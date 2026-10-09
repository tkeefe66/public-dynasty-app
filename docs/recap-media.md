# Shareable recap episodes

An episode attaches to one published recap revision. The existing
`/share/analyst/<token>` URL shows its video above the article, with captions and
MP4/MP3 downloads. Send link and Copy link continue to share this one URL.
The poster supplies the Open Graph and large Twitter card image for message
previews. Actual preview appearance depends on the receiving message client.

## Produce and publish

1. Save the verified league facts, complete script, selected voice, provider
   settings and generation receipt together outside Git. Cover the full week's
   matchups. Preserve approved voice choices and previous takes. Generate once;
   inspect the saved result before considering another provider request.
2. Export a complete bundle: `video.mp4` (H.264/AAC, faststart), `audio.mp3`,
   `poster.jpg` and `captions.vtt`. Align captions and scene changes to the actual
   narration. Verify audio/video decoding, score accuracy and mobile legibility.
3. Copy the reviewed bundle to the API host through the operator's existing
   Railway workflow. Keep source identifiers in environment/configuration.
4. From the API environment, attach to the current **published** article revision:

```sh
python -m app.publish_recap_media \
  --cache-dir "$TRADE_GRADER_CACHE_DIR" \
  --league-id "$RECAP_LEAGUE_ID" --season "$RECAP_SEASON" --week "$RECAP_WEEK" \
  --revision "$RECAP_ARTICLE_REVISION" --duration-seconds "$RECAP_DURATION" \
  --bundle "$RECAP_BUNDLE_DIR"
```

This command validates the required files, size limits and format signatures,
copies an immutable bundle, then atomically publishes its manifest. It does not
decode media; step 2 remains necessary. It does not create or enable a share
link. Existing links immediately pick up the newly attached episode. Use the
edition's **Share recap** control when a link is needed.

5. Verify the production link while signed out: video loads and seeks, the poster
   is accessible, and both downloads complete. Check a text-message preview on
   an actual recipient device. Use a disposable test edition to verify revocation;
   do not revoke a link people already use merely to test it.

## Storage and access

Media lives beside the archive on the API's persistent cache volume, in
`analyst/<league>/media/<season-week>/`. No public static directory, provider demo
URL or expiring provider asset is used. Every GET/HEAD resolves the active share
token and the current published article revision. Streaming supports HTTP byte
ranges for seeking. Responses are private/no-store; the web proxy streams without
buffering or dropping Content-Length/Content-Range.

Replacing a bundle retires previous asset URLs while retaining files for operator
recovery. Correcting the article hides previous media until an episode is attached
to the new revision. Disabling a share link blocks subsequent page and media
requests; it cannot recall already downloaded files, buffered playback, or cached
message previews. Private results packets cannot receive public media.

This uses the existing one-API-replica/shared-volume assumption. Before scaling
replicas or publishing substantially larger catalogs, move the `AnalystMedia`
storage boundary to a private object store. Keep token/revision checks and avoid
durable public asset URLs. Bundles have no automated deletion policy; monitor the
volume and retain reviewed generation receipts. No weekly provider spend or
automatic publication is scheduled by this feature.
