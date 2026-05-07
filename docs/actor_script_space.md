# Actor script space model

The game does not store one private script per actor.

A level part (`Explorer` or `Expert`) has one global actor block:

```text
actor block
├─ actor_count
├─ actor records, 0x20 bytes each
└─ shared actor bytecode space
```

An actor record is an instance/state object.  Important fields include room,
position, frame/variant, hidden/mode, loop counters, and entry pointers:

```text
script_pc
saved_pc
restart_pc
```

Those pointers are addresses inside the shared script space.  Two actors can
point at the same address, and an actor can jump into code that is not an actor
entry point.  Therefore the editor should use terms like **reachable from A5**
or **entered by A6**, not **owned by A5**.

## Editing rules

- Deleting an actor must not delete its script bytes by default.  The script may
  be shared by another actor or reached by an internal jump.
- Deleting an actor should refuse to proceed if `set_actor_mode_*` instructions
  still reference that actor, unless the user explicitly asks to neutralize
  those references.
- Adding an actor can either append a new tiny script routine or reuse an
  existing `script_pc`/`restart_pc` from another actor or explicit address.
- Any change that changes script byte length is a script-space repack operation:
  actor entry pointers and relative `goto`/`call`/`loop_*` branches must remain
  valid.

## UI implications

The actor list should show actor instance properties and entry pointers.  The
script-space view should show the shared address space, incoming/outgoing jumps,
actor entry refs, actor-mode references, and reachable-code overlays.

Human summaries and path/branch previews are useful heuristics, but the source
of truth is the raw bytecode plus the lossless DSL/assembler.
