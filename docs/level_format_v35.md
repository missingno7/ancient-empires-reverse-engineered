# Ancient Empires level format notes - v35

This build is a cleanup/research pass after comparing v34 against screenshots.

## Confirmed fixes

### Visual compact3 code `0x0E` is not a button

Older builds mapped compact3 visual code `0x0E` to `AE000:039:0` globally. That was wrong.
In normal visual tables, `0x0E` is usually just the current theme decoration:

```text
AE001:(25 + theme):14
```

Real ceiling/floor buttons are length-prefixed control commands, not visual compact3 sprite ids.

### Floor buttons can have `arg_b = 0`

Control command records are length-prefixed. Some floor buttons use command `00/01`, a bottom-ish y value,
and `arg_b = 0`. The renderer now treats y-position as part of the button detection instead of relying only
on a tiny `arg_b` whitelist.

## Additional EXE-derived blind spots

The full disassembly shows additional room-object paths after the terrain/decor passes:

* a six-slot room-gated global array around `DS:437a / 4380 / 4386` used by the draw loop around `0x2e36`;
* a three-byte room-gated marker at the end of each 1000-byte room record: `record[0x3e5..0x3e7]`, used around `0x2e89`.

These are now exposed in `payload_debug` as probes, but they are not drawn in normal game mode yet because the
source table population and sprite mapping are still not fully solved.

## Still open

* actor/enemy storage and path data, including snakes (`AE000:022:20`) and larger enemies (`AE000:020:*`);
* artifact/diamond placement (`AE000:044:0`);
* exact runtime trigger/path links for enemies and moving objects;
* exact role of several post-visual payload sections.

The normal renderer intentionally avoids drawing speculative actors. Use `payload_debug` and
`tools/probe_exe_payload.py` when investigating these sections.
