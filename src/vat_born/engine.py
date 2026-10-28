"""The engine: resolves intents against an open world. A free intent reads a `View` and reports. A timed intent records
facts on a `Txn`, in one transaction, and always takes time."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, final

from vat_born.clock import Tick, game_time
from vat_born.content import Content
from vat_born.dice import Dice
from vat_born.events import (
    Activity,
    CloneWoke,
    Event,
    LookReport,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    Resumed,
    StatusReport,
    TimePassed,
    WorldCreated,
)
from vat_born.intents import FreeIntent, Intent, Look, Status, TimedIntent, Wait, Where
from vat_born.store import LogEntry, Store, Txn, View, WorldError
from vat_born.world import CharacterId, Layer, NodeId, PlaceKind

START_PLACE = PlaceKind("vat_bay")  # every clone wakes in a vat here


@dataclass(frozen=True, slots=True)
class Turn:
    """What one command did: the events for the frontend, and the entries it appended to the log."""

    events: tuple[Event, ...]
    logged: tuple[LogEntry, ...] = ()


@final
class Game:
    """An open world. Create or resume one, call `act` once per command, then `close` it."""

    def __init__(self, store: Store, dice: Dice) -> None:
        self._store = store
        self._dice = dice

    @classmethod
    def create(cls, path: Path, seed: int, content: Content) -> tuple[Self, Turn]:
        """Make a new world at PATH, which must not exist yet, and wake its first clone."""
        start = content.place(START_PLACE)
        store = Store.create(path)
        dice = Dice(seed)
        try:
            with store.transaction(dice) as txn:
                txn.record(WorldCreated(seed))
                txn.record(PlaceAdded(NodeId(1), Layer.DECKS, START_PLACE, start.name, start.description))
                txn.record(CloneWoke(run=1, pc=CharacterId(1), place=NodeId(1), place_name=start.name))
        except BaseException:
            store.close()
            path.unlink()  # a half-made world would only fail later, as "not a world"
            raise
        return cls(store, dice), Turn(txn.facts, txn.logged)

    @classmethod
    def resume(cls, path: Path, seed: int | None) -> tuple[Self, Turn]:
        """Open the existing world at PATH. If SEED is given, it must be the world's."""
        store = Store.open(path)
        view = store.view()
        stored = view.seed()
        if seed is not None and seed != stored:
            store.close()
            raise WorldError(f"{path} is the world for seed {stored}, not {seed}")
        report = Resumed(stored, view.run(), game_time(view.tick()), view.pc_place().name)
        return cls(store, Dice(stored)), Turn((report,))

    def act(self, intent: Intent) -> Turn:
        match intent:
            case Status() | Where() | Look():
                return Turn(_resolve_free(intent, self._store.view()))
            case Wait():
                return self._timed(intent)
            case _:
                assert_never(intent)

    def close(self) -> None:
        self._store.close()

    def _timed(self, intent: TimedIntent) -> Turn:
        with self._store.transaction(self._dice) as txn:
            start = txn.tick()
            _resolve_timed(intent, txn)
            end = txn.tick()
            assert end > start, f"{intent} took no time"
        events: list[Event] = [*txn.facts]
        before, after = game_time(start), game_time(end)
        if after != before:
            events.append(PhaseChanged(before, after))
        return Turn(tuple(events), txn.logged)


def _resolve_free(intent: FreeIntent, view: View) -> tuple[Event, ...]:
    match intent:
        case Status():
            return (StatusReport(game_time(view.tick()), view.run()),)
        case Where():
            return (PlaceReport(view.pc_place().name),)
        case Look():
            place = view.pc_place()
            return (LookReport(place.name, place.description),)
        case _:
            assert_never(intent)


def _resolve_timed(intent: TimedIntent, txn: Txn) -> None:
    match intent:
        case Wait(ticks=ticks):
            start = txn.tick()
            txn.record(TimePassed(start, Tick(start + ticks), Activity.WAITING))
        case _:
            assert_never(intent)
