# Vat-Born

A text-first survival/base-building roguelike aboard a colony ship. The engine is a skeleton so far: you can start a
world, look around, walk between the rooms around the vat bay and out through the bulkhead onto the decks beyond it
— a corridor, side rooms, and a ladder down, laid out by the world's seed — check the time, ask where you are and
the shortest known way home to the vat bay, read the map of the places you've been, and let time pass.

The Python engine owns world state, time, probabilities, rolls, and outcomes. A future LLM integration may parse
player intent and narrate resolved events, but may not change the rules or state directly.

## Playing

```sh
uv run vat-born                 # resume the last world you played, or start a new one
uv run vat-born --seed 42       # play world 42, making it on first use
uv run vat-born --world PATH    # play the world stored in PATH
```

Worlds are SQLite files in `$XDG_DATA_HOME/vat-born` (by default `~/.local/share/vat-born`), one per seed. Type
`help` in the game for the commands.

## Development

Requires [uv](https://docs.astral.sh/uv/), which provides Python 3.14 and the pinned dev tools.

```sh
uv sync                                                                # create .venv from uv.lock
uv run ruff check --fix && uv run ruff format && uv run basedpyright   # lint, format, type-check
uv run pytest                                                          # replay the scenario transcripts
uv run pytest --regen                                                  # rewrite them after an intended change
git config core.hooksPath .githooks                                    # once per clone: commits run all of it
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
