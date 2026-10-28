"""The world's randomness. Every draw comes from a stream keyed by what it is for, never from one shared generator: a
new draw in one system can't shift the outcomes of another, and a resumed world needs no saved generator state.

Game code doesn't use this module directly. Chances go through `Txn.roll`, which logs each roll with its odds, and
other draws, such as worldgen's choices, through `Txn.stream`."""

import json
import random
from dataclasses import dataclass
from typing import final

type Key = str | int
type Stream = random.Random


@dataclass(frozen=True, slots=True)
class Modifier:
    """One named adjustment to a chance: `Modifier("lamp", 0.15)` adds 15 points."""

    reason: str
    delta: float


@dataclass(frozen=True, slots=True)
class Odds:
    """A chance as the player sees it: a base rate plus named modifiers."""

    base: float
    modifiers: tuple[Modifier, ...] = ()

    def __post_init__(self) -> None:
        assert 0.0 <= self.base <= 1.0, f"base rate {self.base} is not a probability"

    @property
    def chance(self) -> float:
        return min(1.0, max(0.0, self.base + sum(modifier.delta for modifier in self.modifiers)))


@final
class Dice:
    def __init__(self, seed: int) -> None:
        self._seed = seed

    def stream(self, *key: Key) -> Stream:
        """The generator for KEY. The same key always gives the same sequence, whatever else has been drawn."""
        # random.Random hashes a str seed with SHA-512, so the sequence doesn't depend on PYTHONHASHSEED.
        return random.Random(json.dumps([self._seed, *key]))
