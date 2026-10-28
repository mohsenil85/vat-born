"""Plays the same commands on many seeds and checks only that nothing crashes, the engine's own assertions included.
The command list grows with the game."""

from pathlib import Path

import pytest

from tests.harness import play

COMMANDS = (
    "status",
    "where",
    "look",
    "north",
    "south",
    "east",
    "west",
    "west",
    "east",
    "up",
    "go",
    "wait",
    "wait 3 hours",
    "status",
    "wait 2 days",
    "where",
    "wait 90 minutes",
    "status",
)


@pytest.mark.parametrize("seed", range(20))
def test_sweep(seed: int, tmp_path: Path) -> None:
    play(tmp_path / "world.db", seed, COMMANDS, hash_seed=seed)
