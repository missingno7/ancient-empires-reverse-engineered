# Level format notes - v36

This version is a cleanup of the control object interpretation.

## Confirmed/strong model

* Level resources still parse as two difficulty parts: Explorer and Expert.
* Each part has 13 fixed 1000-byte room records. Not all records are valid used rooms; some are empty/placeholders or data-like records.
* Terrain is the 38x18 byte grid at room record +2.
* Ropes and conveyors are special terrain tile codes, not payload sprites.
* `0x07` is invisible collision/support.
* `0x0F` and `0x1F` are conveyor belt terrain codes. The visible strip is composed from AE000:038 left/middle/right parts.
* Background/theme decoration uses the visual compact3 table and AE001:(25+theme), with `code & 0x3f` as sprite index and `code & 0x40` as horizontal mirror flag.

## v36 control command fix

Length-prefixed control records have the form:

```text
[length] [command] [x_raw] [y_raw] [arg_a] [arg_b] ...
```

The length byte is not an object type.  In v36, command `0x00` is treated as a button/trigger visual regardless of the link id.  This fixes rooms where multiple buttons had arg/link ids that older builds skipped.  The link fields are puzzle/platform trigger metadata, not sprite ids.

Command `0x01` is now hidden from normal rendering and exposed only in payload debug, because it appears to be state/platform/door metadata rather than a simple button sprite.

## Still open

* Full actor/enemy/item table: player start, snakes, diamond, green creature, spider paths, etc.
* Exact coordinate model for all actor paths.
* Exact trigger graph linking button records to moving platforms and puzzle blocks.
