# Level format notes - v40 actor path overlay

Enemies are still modeled as runtime actors from the difficulty-part actor table
at part offset `0x2754`.  The important new cleanup is that the renderer/editor
now keeps three separate concepts apart:

1. actor start anchor: `record[0x02..0x05]` gives the initial logical x/y;
2. actor bitmap origin: a per-frame-family origin table converts that anchor to
   sprite top-left; the current defaults preserve the old `(-12,-12)` alignment
   but are now centralized in `coordinates.ACTOR_ORIGIN_BY_FRAME_MIN`;
3. actor script path: `record[0x0d..0x0e]` points to a bytecode stream inside the
   actor block.  The editor decodes the recurring movement form
   `0E dx dy flags 04/05 rel duration` as a segment and draws the estimated
   patrol polyline in the overlay.

This is deliberately a research overlay, not a complete VM.  Unknown opcodes are
kept as commands but do not affect position.  Backward jumps are treated as loop
markers so the path preview does not run forever.  The useful result is that
snakes, spiders, bats and ladybug-like enemies now expose their "move from start,
wait/update, move back" routes instead of looking like static sprites with no AI.

The player start is intentionally not changed because it comes from the level
header and already aligns well against screenshots.
