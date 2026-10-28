"""Plays the same commands on many seeds and checks only that nothing crashes, the engine's own assertions included.
The command list grows with the game."""

from pathlib import Path

import pytest

from tests.harness import play

COMMANDS = (
    "west",
    "search",
    "search",
    "search",
    "look",
    "east",
    "drink",
    "rest",
    "status",
    "where",
    "map",
    "look",
    "north",
    "north",
    "north",
    "east",
    "west",
    "west",
    "east",
    "north",
    "down",
    "map",
    "east",
    "east",
    "where",
    "west",
    "west",
    "up",
    "north",
    "east",
    "west",
    "north",
    "north",
    "north",
    "south",
    "where",
    "map",
    "wait",
    "wait 3 hours",
    "status",
    "wait 2 days",
    "where",
    "wait 90 minutes",
    "status",
    "rest",
    "drink",
    "sleep until dawn",
    "rest",
    "status",
    "search",
    "search",
    "look",
    "search",
)


@pytest.mark.parametrize("seed", range(20))
def test_sweep(seed: int, tmp_path: Path) -> None:
    play(tmp_path / "world.db", seed, COMMANDS, hash_seed=seed)
