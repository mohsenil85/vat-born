# Vat-Born

A text-first survival/base-building roguelike aboard a colony ship. This repository is at the engine-scaffold stage;
there is no playable game yet.

The Python engine will own world state, time, probabilities, rolls, and outcomes. A future LLM integration may parse
player intent and narrate resolved events, but may not change the rules or state directly.

## Development

Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/vat-born
```

## First slice

- Seeded single-layer deck graph and vat spawn.
- SQLite world state and append-only event log; replayable canned intents without a model.
- Free observations versus timed actions; scheduler and interruptible long actions.
- Explicit odds, telegraphed hazard clocks, and a small embodied base.
- Permadeath, persistent world/bones, and respawn from a vat.

Voice, additional layers, and AI-authored rules are deferred. See the [working design document](docs/design.md) for the
full vision and open questions. The Python choice is settled for this implementation; other open questions remain.
