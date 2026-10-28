"""Replays each transcript in tests/scenarios/ and checks the game still plays it the same way: straight through,
under another hash seed, and stopped halfway and resumed in a new process.

A transcript is `#` header lines, one of them `# seed: N`, then a blank line and the session as the player saw it.
Lines starting with `> ` are the commands, and each command's log entries follow its text. A `# show-log: all`
header line adds the log of making the world, which only scenarios about worldgen want. To add a scenario, write the
header and the commands, run `uv run pytest --regen`, and read what the game filled in."""

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Self, cast

import pytest

from tests.harness import play

SCENARIOS = Path(__file__).parent / "scenarios"


@dataclass(frozen=True, slots=True)
class Scenario:
    path: Path
    header: str
    seed: int
    log: str  # what --show-log shows: "turns", or "all" to include making the world
    body: str

    @classmethod
    def read(cls, path: Path) -> Self:
        lines = path.read_text().splitlines(keepends=True)
        n = next((i for i, line in enumerate(lines) if not line.startswith("#")), len(lines))
        seeds = _header(lines[:n], "seed")
        if len(seeds) != 1 or not seeds[0].isdecimal():
            pytest.fail(f"{path.name}: the header needs exactly one '# seed: N' line", pytrace=False)
        logs = _header(lines[:n], "show-log")
        if logs not in ([], ["all"]):
            pytest.fail(f"{path.name}: '# show-log: all' is the only show-log header", pytrace=False)
        log = logs[0] if logs else "turns"
        return cls(path, "".join(lines[:n]), int(seeds[0]), log, "".join(lines[n:]).removeprefix("\n"))

    @property
    def commands(self) -> list[str]:
        return [line.removeprefix("> ") for line in self.body.splitlines() if line.startswith("> ")]

    def rewrite(self, body: str) -> None:
        self.path.write_text(f"{self.header}\n{body}")


@pytest.mark.parametrize("path", [pytest.param(path, id=path.stem) for path in sorted(SCENARIOS.glob("*.txt"))])
def test_scenario(path: Path, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    scenario = Scenario.read(path)
    commands = scenario.commands
    straight = play(tmp_path / "straight.db", scenario.seed, commands, log=scenario.log)
    if cast("bool", request.config.getoption("--regen")):
        if straight != scenario.body:
            scenario.rewrite(straight)
    else:
        _same(
            scenario.body,
            straight,
            "The game no longer plays this transcript. If your change means to alter it, run "
            "`uv run pytest --regen` and review the diff.",
        )
    hashed = play(tmp_path / "hashed.db", scenario.seed, commands, hash_seed=1, log=scenario.log)
    _same(straight, hashed, "Under another PYTHONHASHSEED the game played differently: set order or hash() leaks.")
    half = len(commands) // 2
    first = play(tmp_path / "split.db", scenario.seed, commands[:half], log=scenario.log)
    second = play(tmp_path / "split.db", scenario.seed, commands[half:], log=scenario.log)
    _same(straight, first + _after_startup(second), "Stopped halfway and resumed, the game played differently.")


def _header(lines: list[str], key: str) -> list[str]:
    """The values of the `# KEY: value` header lines."""
    return [line.removeprefix(f"# {key}:").strip() for line in lines if line.startswith(f"# {key}:")]


def _after_startup(transcript: str) -> str:
    """The transcript from its first command on, without the banner a resumed world prints."""
    lines = transcript.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("> ")), len(lines))
    return "".join(lines[start:])


def _same(expected: str, actual: str, problem: str) -> None:
    if actual != expected:
        diff = difflib.unified_diff(
            expected.splitlines(keepends=True), actual.splitlines(keepends=True), "expected", "played"
        )
        pytest.fail(f"{problem}\n{''.join(diff)}", pytrace=False)
