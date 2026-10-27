# Vat-Born

A text-first survival/base-building roguelike aboard a colony ship. This repository is at the engine-scaffold stage;
there is no playable game yet.

The Python engine will own world state, time, probabilities, rolls, and outcomes. A future LLM integration may parse
player intent and narrate resolved events, but may not change the rules or state directly.

## Development

Requires [uv](https://docs.astral.sh/uv/), which provides Python 3.14 and the pinned dev tools.

```sh
uv sync                                                                # create .venv from uv.lock
uv run vat-born                                                        # run the scaffold
uv run ruff check --fix && uv run ruff format && uv run basedpyright   # lint, format, type-check
uv run pytest
git config core.hooksPath .githooks                                    # once per clone: commits run the check
```

Coding agents: read [AGENTS.md](AGENTS.md) first.

## First slice

- Seeded single-layer deck graph and vat spawn.
- SQLite world state and append-only event log; replayable canned intents without a model.
- Free observations versus timed actions; scheduler and interruptible long actions.
- Explicit odds, telegraphed hazard clocks, and a small embodied base.
- Permadeath, persistent world/bones, and respawn from a vat.

Voice, additional layers, and AI-authored rules are deferred. See the [working design document](docs/design.md) for the
full vision, and the [build plan](docs/plan.md) for the slice's decisions and build order.
