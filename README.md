# Vat-Born

A text-first survival/base-building roguelike aboard a colony ship. The first slice is playable through death and
the next clone (milestones M0 to M5 in the [build plan](docs/plan.md)):

- Wake in a clone vat and explore the rooms around the vat bay, then the decks beyond the bulkhead, laid out by the
  world's seed. `look`, `map`, and `where` (with the way home) take no time.
- Time wears on the clone: thirst, hunger, and fatigue build and show in `status`. Drink at the tap in the vat bay,
  rest or sleep, and eat what you find.
- Search a place for what it hides, an hour at a time, against odds you can see, until it has nothing left. Take,
  carry, and drop what you find; a canteen carries water, and a lamp helps a search.
- Dangers gather in the background and show themselves in signs: a predator that leaves tracks, then a kill, then
  cries in the night before it hunts, and an air recycler that falters before it fails. `status` names the dangers
  you've come across, with their odds.
- The hunting predator attacks a clone that lingers. Fight or flee, each a gamble whose odds you see before you
  commit; wounds heal with time, and a third kills. When the air fails, breath runs short at home until you step out
  to the decks, or repair the recycler, a long job that keeps its progress.
- Death doesn't end the world. The body stays where it fell with everything it carried, the ship goes on for a day
  or three, and the next clone wakes in the vat bay, knowing the map and nothing else.

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
