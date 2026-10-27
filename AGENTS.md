# Vat-Born — agent guide

A text-first survival/base-building roguelike aboard a colony ship, written mostly by coding agents. The engine is a
scaffold: there is no playable game yet. The tooling is strict on purpose, so lean on it.

- `docs/design.md` is the source of truth for what we're building. Read the sections your task touches before you
  start. If a change would contradict it, stop and ask. If a change settles one of its open questions (§16), update
  the doc in the same change.
- `src/vat_born/` is the package (src layout); `vat_born.cli:main` is the `vat-born` command.

## Commands

Everything goes through uv. Don't use `pip`, `python -m venv`, or an activated venv, and don't call the globally
installed `ruff` or `pyright` on this machine: `uv run` uses the versions pinned in `uv.lock`.

```sh
uv sync                     # create or refresh .venv from uv.lock (uv run does this too)
uv run vat-born             # run the game
uv run ruff check --fix && uv run ruff format && uv run basedpyright   # the check
uv add <pkg>                # add a runtime dependency (ask first)
uv add --dev <pkg>          # add a dev-only tool
git config core.hooksPath .githooks   # once per clone: every commit runs the check
```

## Done means

- The check passes clean. basedpyright warnings fail the run, same as errors.
- Every commit reruns the check on exactly what is staged, in a throwaway copy (`.githooks/pre-commit`), so `git add`
  every file your change needs. Never commit with `--no-verify`.
- If you changed something a player can see, run `uv run vat-born` and look at it.
- No unit tests. Integration tests are being set up separately in `tests/`; leave that directory alone, and until this
  file says how to run them, there is no test step. To try something out, run the game or a throwaway script outside
  the repo.
- `docs/design.md` and `README.md` still match the code.

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
  diffs, rolls), `enum.StrEnum` for closed sets, and `typing.NewType` for IDs (`NodeId`, `ItemId`) so they can't be
  swapped. Dispatch over a closed set with `match` and end with `case _: assert_never(x)`, so a missed case fails the
  type check.
- `Any` only exists at I/O edges such as sqlite3 rows and `json.loads`. `cast()` it to a precise type right there, as
  in `cast("tuple[int, str] | None", cursor.fetchone())`. For untrusted input such as model output, cast to `object`
  and narrow with `match`/`isinstance`. Every trust point is then a greppable `cast(`.
- Fail loudly. Catch only exceptions you can handle. No blanket `except`, swallowed errors, or placeholder return
  values that hide a bug.
- Use absolute imports (relative ones are lint errors), `pathlib`, and timezone-aware datetimes.
- Comments say why, not what. Add docstrings where they tell the reader something the signature doesn't.
- Build what the task needs. The design describes later layers and modes; leave the seams it asks for, but don't
  build ahead (pillar 5: build the game, not the engine).

## Engine invariants

These come from `docs/design.md` and bind every change:

- Code owns truth, the model owns words. Code that calls an LLM returns intents or prose. It never computes odds,
  rolls, or writes game state; the engine validates intents and applies every change.
- Same seed and same inputs give the same outcomes. Take randomness from the world's seeded `random.Random`, passed in
  explicitly; the module-level `random` functions are banned by lint. Wall-clock time, `hash()`, and set iteration
  order must never affect an outcome, so sort before you iterate.
- The event log is append-only: never update or delete log rows.
- Free actions (`look`, `examine`, `inventory`, …) only describe what is already in the DB at the PC's knowledge
  level. Only timed actions create knowledge.
- The engine computes odds as a base rate plus named modifiers, and the player can see them.
- The engine emits structured events, and only frontends write to the terminal. `print` is a lint error outside
  `src/vat_born/cli.py`; add a new frontend module to that per-file ignore when you create one.
- SQL takes `?` parameters, never string formatting.
