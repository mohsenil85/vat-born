# Vat-Born — agent guide

A text-first survival/base-building roguelike aboard a colony ship, written mostly by coding agents. The engine is a
skeleton so far (see Status in `docs/plan.md`). The tooling is strict on purpose, so lean on it.

- `docs/design.md` is the source of truth for what we're building. Read the sections your task touches before you
  start. If a change would contradict it, stop and ask. If a change settles one of its open questions (§16), update
  the doc in the same change.
- `docs/plan.md` narrows the design for the first build and sets the build order. Where the two differ (no morale
  yet, typed commands before free text), follow the plan. Build to its decisions; don't re-decide them in code. If a
  task needs a decision the plan doesn't make, report it as a question instead of guessing.
- `src/vat_born/` is the package (src layout); `vat_born.cli:main` is the `vat-born` command.

## Commands

Everything goes through uv. Don't use `pip`, `python -m venv`, or an activated venv, and don't call the globally
installed `ruff` or `pyright` on this machine: `uv run` uses the versions pinned in `uv.lock`.

```sh
uv sync                     # create or refresh .venv from uv.lock (uv run does this too)
uv run ruff check --fix && uv run ruff format && uv run basedpyright   # the check
uv run pytest               # the tests: replay every scenario transcript
uv run pytest --regen       # rewrite the transcripts from what the game does now, then read the diff
uv add <pkg>                # add a runtime dependency (ask first)
uv add --dev <pkg>          # add a dev-only tool
git config core.hooksPath .githooks   # once per clone: every commit runs the check and the tests
```

## Where things live

All in `src/vat_born/`:

- `cli.py`: arguments, choosing the world file, and the REPL. The only module that prints.
- `commands.py`: a typed line to a command (an intent, or help or quit), and the help text.
- `intents.py`: what the engine can be asked to do, split into free and timed intents.
- `engine.py`: `Game`, which resolves free intents against a read-only `View` and timed ones on a `Txn`.
- `events.py`: facts (changes to the world, always logged) and reports (answers, never logged).
- `store.py`: the SQLite schema and all the SQL: `View`, `Txn`, and how each fact is applied.
- `dice.py`: keyed random streams and `Odds`.
- `clock.py`: ticks, days, and phases.
- `worldgen.py`: the decks beyond the home section, laid out from the seed as facts for the engine to record.
- `render.py`: events to the text a player reads.
- `content/`: the TOML content (`places.toml`, the fixed `home.toml` section, worldgen's `decks.toml` tables) and
  the loader that checks it.

## Adding an action

1. Add an intent to `intents.py`, in `FreeIntent` or `TimedIntent`.
2. Parse it in `commands.py` and add it to `HELP`.
3. Resolve it in `engine.py`:
   - a free action reads the `View` and returns reports;
   - a timed action records facts on the `Txn`. Each new fact needs a dataclass in `events.py`, a case in
     `store.py`'s `_apply` (bump `SCHEMA_VERSION` if the schema changes), and a case in `render.py`. A timed action
     that can't be done records nothing and returns a report saying why; no time passes.
4. basedpyright fails until every `match` covers the new types, which is how you find the places left to change.
5. Your task names the scenarios that show the action. Regenerate them and read every line.

## Running the game

The REPL needs a terminal, so agents play it through a [zmx](https://zmx.sh) session. Use a session name unique to
your task and a scratch world, never the player's, and remove both when you're done. `zmx run` types the command into
a login shell whose `PATH` differs from yours, so pass `uv`'s full path and the directory as separate words, as below.

```sh
s=vat-born-<task>; w=$(mktemp -d)
zmx run "$s" -d "$(command -v uv)" --directory "$PWD" run vat-born --world "$w/world.db" --seed 1
zmx send "$s" $'status\r'             # type a command and press Enter
zmx history "$s" | tail -n 40         # read the screen
zmx kill "$s"; rm -rf "$w"            # done
```

`zmx wait "$s"` blocks until the game exits, so only use it after you've quit. Add `--show-log` to see what each
command adds to the event log, or `--show-log=all` to see the world being made as well. For a quick look without a
terminal, pipe the commands in:
`printf 'status\nwait 2 hours\n' | uv run vat-born --world "$w/world.db" --seed 1`.

## Done means

- The check passes clean. basedpyright warnings fail the run, same as errors.
- `uv run pytest` passes. If your change is meant to alter what a scenario shows, run `uv run pytest --regen`, read
  every changed line of `git diff tests/scenarios`, and list each changed transcript in your report with the reason.
  A transcript that changed when it shouldn't have is a bug: fix the code, not the transcript.
- Every commit reruns the check and the tests on exactly what is staged, in a throwaway copy (`.githooks/pre-commit`),
  so `git add` every file your change needs. Never commit with `--no-verify`.
- If you changed something a player can see, play it through zmx (see Running the game) and look at it.
- No unit tests. The tests belong to the orchestrator: the scenario transcripts, a crash sweep over many seeds, and a
  few world-file tests. Don't add, delete, or hand-edit any of them unless your task says to. To try something out,
  run the game or a throwaway script outside the repo.
- `docs/design.md` and `README.md` still match the code.

## Workers

If an orchestrator gave you a task, these hold unless the task says otherwise:

- Do what the task asks and no more. Don't touch `AGENTS.md`, `docs/`, `pyproject.toml`, `.githooks/`, `scripts/`,
  or `uv.lock`, and in `tests/` only the files your task names.
- Don't commit; the orchestrator commits your work through the pre-commit hook.
- Your report lists every file you changed, each transcript included, with the reason it changed.
- If the task contradicts itself or the code, make the smallest change that resolves it, and flag it under
  Questions.

## Python and tooling

- Python 3.14, pinned in `.python-version`. Write current Python: `X | None`, builtin generics, `type` aliases, PEP 695
  generics (`def first[T](xs: list[T]) -> T`), `@override` on overriding methods. Annotations are lazy in 3.14, so
  never add `from __future__ import annotations`.
- Lint is ruff with every rule enabled minus a short, commented ignore list in `pyproject.toml`. Types are basedpyright
  in `recommended` mode: nearly every rule on, including `reportAny`.
- Fix the code, not the checker. If a suppression is truly warranted, scope it to one line and one rule, and give the
  reason: `# noqa: PLR0913 - <why>` or `# pyright: ignore[reportAny] - <why>`. Bare `# type: ignore` is not honored.
  Don't loosen `pyproject.toml`, edit `.githooks/`, or change this file to get a clean run; propose the change
  instead.
- Dependencies: stdlib first. Ask before adding a runtime dependency, and check the exact name on PyPI before you
  install it (hallucinated package names get squatted). Use `uv add` and `uv remove`; never edit `uv.lock` by hand.

## Code conventions

- Model data with types, not dicts. Use `@dataclass(frozen=True, slots=True)` for values (intents, events, state
  diffs, rolls), `enum.StrEnum` for closed sets, and `typing.NewType` for IDs (`NodeId`, `CharacterId`) so they can't
  be swapped. Dispatch over a closed set with `match` and end with `case _: assert_never(x)`, so a missed case fails
  the type check.
- `Any` only exists at I/O edges such as sqlite3 rows and `json.loads`. `cast()` it to a precise type right there, as
  in `cast("tuple[int, str] | None", cursor.fetchone())`. For untrusted input such as model output, cast to `object`
  and narrow with `match`/`isinstance`. Every trust point is then a greppable `cast(`.
- Fail loudly. Catch only exceptions you can handle. No blanket `except`, swallowed errors, or placeholder return
  values that hide a bug. Assert the engine's own invariants.
- Use absolute imports (relative ones are lint errors) and `pathlib`.
- Comments say why, not what. Add docstrings where they tell the reader something the signature doesn't.
- Build what the task needs. The design describes later layers and modes; leave the seams it asks for, but don't
  build ahead (pillar 5: build the game, not the engine).

## Engine invariants

These come from `docs/design.md`, and the engine's structure enforces most of them:

- Code owns truth, the model owns words. Code that calls an LLM returns intents or prose. It never computes odds,
  rolls, or writes game state; the engine validates intents and applies every change.
- Same seed and same inputs give the same outcomes. All randomness comes from the world's dice, through the `Txn`:
  `txn.roll(odds, purpose, *key)` for a chance and `txn.stream(purpose, *key)` for any other draw. Each draw is keyed
  by what it's for, so adding one never shifts another. `random` and the wall clock are lint errors outside
  `dice.py`. `hash()` and set iteration order must never affect an outcome, so sort before you iterate; the tests
  replay every scenario under a second hash seed to catch it.
- State changes only through `txn.record(fact)`, which applies the fact and appends it to the event log. The schema
  rejects updates and deletes on the log.
- Free actions get a read-only `View`, and SQLite refuses writes outside a transaction, so a free action can only
  describe what is already in the DB at the PC's knowledge level. Only timed actions create knowledge, and every
  timed action takes at least one tick.
- Every chance is an `Odds`, a base rate plus named modifiers, and the player can see the breakdown.
- The engine emits events, and only frontends write to the terminal. `print` is a lint error outside
  `src/vat_born/cli.py`; add a new frontend module to that per-file ignore when you create one.
- SQL lives in `store.py` and takes `?` parameters, never string formatting.
