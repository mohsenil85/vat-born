"""The engine: resolves intents against an open world. A free intent reads a `View` and reports. A timed intent records
facts on a `Txn`, in one transaction, and always takes time."""

import heapq
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, final

from vat_born import worldgen
from vat_born.clock import TICKS_PER_HOUR, Tick, game_time, ticks_until
from vat_born.content import Content
from vat_born.dice import Dice, Modifier, Odds
from vat_born.events import (
    CloneWoke,
    Event,
    Interrupted,
    InventoryReport,
    ItemDropped,
    ItemFound,
    ItemHidden,
    ItemStack,
    ItemTaken,
    LookReport,
    MapEntry,
    MapReport,
    NeedLevel,
    NeedMet,
    NeedsChanged,
    NeedWorsened,
    NoPath,
    NotCarried,
    NotHere,
    NothingCarried,
    NothingHere,
    NotTired,
    NoWater,
    NowhereLeft,
    PathAdded,
    PcMoved,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    PlaceSearchedBare,
    PlaceVisited,
    Report,
    Resumed,
    Route,
    StatusReport,
    TimePassed,
    WhichOne,
    WorldCreated,
)
from vat_born.intents import (
    Drink,
    Drop,
    DropAll,
    FreeIntent,
    Intent,
    Inventory,
    Look,
    Map,
    Move,
    Rest,
    RestUntil,
    Search,
    Status,
    Take,
    TakeAll,
    TimedIntent,
    Wait,
    WaitUntil,
    Where,
)
from vat_born.needs import Activity, Need, Needs, level, tick
from vat_born.store import LogEntry, Store, Txn, View, WorldError
from vat_born.world import CharacterId, Direction, Item, ItemId, ItemKind, Layer, NodeId


@dataclass(frozen=True, slots=True)
class Turn:
    """What one command did: the events for the frontend, and the entries it appended to the log."""

    events: tuple[Event, ...]
    logged: tuple[LogEntry, ...] = ()


@final
class Game:
    """An open world. Create or resume one, call `act` once per command, then `close` it."""

    def __init__(self, store: Store, dice: Dice, content: Content) -> None:
        self._store = store
        self._dice = dice
        self._content = content

    @classmethod
    def create(cls, path: Path, seed: int, content: Content) -> tuple[Self, Turn]:
        """Make a new world at PATH, which must not exist yet, and wake its first clone in the home section."""
        home = content.home
        nodes = {kind: NodeId(n) for n, kind in enumerate(home.places, start=1)}
        start = content.place(home.start)
        store = Store.create(path)
        dice = Dice(seed)
        try:
            with store.transaction(dice) as txn:
                txn.record(WorldCreated(seed))
                for kind in home.places:
                    place = content.place(kind)
                    txn.record(PlaceAdded(nodes[kind], Layer.DECKS, kind, place.name, place.description, place.water))
                for way in home.paths:
                    txn.record(PathAdded(nodes[way.origin], nodes[way.to], way.direction, way.ticks))
                stream = txn.stream("worldgen", "decks")
                beyond = worldgen.decks(content, stream, nodes[home.gate.place], NodeId(len(home.places) + 1))
                for fact in beyond:
                    txn.record(fact)
                placed = [(nodes[kind], kind) for kind in home.places]
                placed += [(fact.place, fact.kind) for fact in beyond if isinstance(fact, PlaceAdded)]
                item = 1
                for node, kind in placed:  # node ID order: the home places, then the decks' places from first up
                    for found in worldgen.finds(content, kind, txn.stream("worldgen", "finds", node)):
                        txn.record(ItemHidden(ItemId(item), found, node))
                        item += 1
                txn.record(CloneWoke(run=1, pc=CharacterId(1), place=nodes[home.start], place_name=start.name))
                txn.record(PlaceVisited(nodes[home.start]))
            turn = Turn((*txn.facts, _look(store.view(), content)), txn.logged)
        except BaseException:
            store.close()
            path.unlink()  # a half-made world would only fail later, as "not a world"
            raise
        return cls(store, dice, content), turn

    @classmethod
    def resume(cls, path: Path, seed: int | None, content: Content) -> tuple[Self, Turn]:
        """Open the existing world at PATH. If SEED is given, it must be the world's."""
        store = Store.open(path)
        view = store.view()
        stored = view.seed()
        if seed is not None and seed != stored:
            store.close()
            raise WorldError(f"{path} is the world for seed {stored}, not {seed}")
        report = Resumed(stored, view.run(), game_time(view.tick()), view.pc_place().name)
        return cls(store, Dice(stored), content), Turn((report,))

    def act(self, intent: Intent) -> Turn:
        match intent:
            case Status() | Where() | Look() | Map() | Inventory():
                return Turn(_resolve_free(intent, self._store.view(), self._content))
            case (
                Wait()
                | WaitUntil()
                | Move()
                | Drink()
                | Search()
                | Rest()
                | RestUntil()
                | Take()
                | TakeAll()
                | Drop()
                | DropAll()
            ):
                return self._timed(intent)
            case _:
                assert_never(intent)

    def close(self) -> None:
        self._store.close()

    def _timed(self, intent: TimedIntent) -> Turn:
        with self._store.transaction(self._dice) as txn:
            start = txn.tick()
            reports = _resolve_timed(intent, txn, self._content)
            end = txn.tick()
        if not txn.facts:  # refused: nothing changed and no time passed
            assert reports, f"{intent} did nothing and said nothing"
            return Turn(reports)
        assert end > start, f"{intent} took no time"
        before, after = game_time(start), game_time(end)
        notices = (PhaseChanged(before, after),) if after != before else ()
        return Turn((*txn.facts, *notices, *reports), txn.logged)


def _resolve_free(intent: FreeIntent, view: View, content: Content) -> tuple[Event, ...]:
    match intent:
        case Status():
            needs = view.needs()
            levels = tuple(NeedLevel(need, level(need, needs.count(need))) for need in Need)
            return (StatusReport(game_time(view.tick()), view.run(), levels),)
        case Where():
            return (PlaceReport(view.pc_place().name, _route_home(view)),)
        case Look():
            return (_look(view, content),)
        case Inventory():
            return (InventoryReport(_stacked(view.carried(), content)),)
        case Map():
            here = view.pc_place().id
            entries = tuple(
                MapEntry(place.name, place.id == here, view.exits(place.id))
                for place in (view.place(node) for node in view.visited())
            )
            return (MapReport(entries),)
        case _:
            assert_never(intent)


def _resolve_timed(intent: TimedIntent, txn: Txn, content: Content) -> tuple[Report, ...]:
    """Do what the intent says, recording its facts, and return the reports to show after them. A refused action
    records nothing and returns the report that says why."""
    match intent:
        case Wait(ticks=ticks):
            return _pass(txn, ticks, Activity.WAITING, interruptible=True)
        case WaitUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), Activity.WAITING, interruptible=True)
        case Move(direction=direction):
            place = txn.pc_place()
            way = next((out for out in txn.exits(place.id) if out.direction == direction), None)
            if way is None:
                return (NoPath(direction),)
            reports = _pass(txn, way.ticks, Activity.WALKING, interruptible=False)
            txn.record(PcMoved(txn.pc(), place.id, way.to, direction, way.place_name))
            if not txn.is_visited(way.to):
                txn.record(PlaceVisited(way.to))
            return (*reports, _look(txn, content))
        case Drink():
            if not txn.pc_place().water:
                return (NoWater(),)
            return _pass(txn, 1, Activity.DRINKING, interruptible=False)
        case Search():
            return _search(txn, content)
        case Take(words=words):
            place = txn.pc_place()
            match _meant(words, txn.items_at(place.id), content):
                case None:
                    return (NotHere(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _handle(txn, content, items, taking=True)
        case TakeAll():
            items = txn.items_at(txn.pc_place().id)
            return (NothingHere(),) if not items else _handle(txn, content, items, taking=True)
        case Drop(words=words):
            match _meant(words, txn.carried(), content):
                case None:
                    return (NotCarried(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _handle(txn, content, items, taking=False)
        case DropAll():
            items = txn.carried()
            return (NothingCarried(),) if not items else _handle(txn, content, items, taking=False)
        case Rest(ticks=ticks):
            if ticks is None:  # until rested
                fatigue = txn.needs().fatigue
                if fatigue == 0:
                    return (NotTired(),)
                ticks = (fatigue + 1) // 2  # just long enough to reach 0
            return _pass(txn, ticks, Activity.RESTING, interruptible=True)
        case RestUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), Activity.RESTING, interruptible=True)
        case _:
            assert_never(intent)


# A search takes an hour, and rolls to turn up the next hidden thing: 50%, less when fatigue clouds the search. A
# carried hand lamp would add its bonus here too, when carrying arrives later in M3.
_SEARCH_TICKS = TICKS_PER_HOUR
_SEARCH_BASE = 0.50
_SEARCH_VERY_TIRED = Modifier("very tired", -0.10)
_SEARCH_EXHAUSTED = Modifier("exhausted", -0.20)


def _search(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Spend an hour searching where the PC is. A place hides only so much: once a search finds nothing left, the
    clone knows not to search there again."""
    place = txn.pc_place()
    if txn.searched_bare(place.id):
        return (NowhereLeft(),)
    start = txn.tick()
    reports = _pass(txn, _SEARCH_TICKS, Activity.SEARCHING, interruptible=True)
    if txn.tick() - start < _SEARCH_TICKS:  # a need stopped the search early, and an interrupted search finds nothing
        return reports
    hidden = txn.next_hidden(place.id)
    if hidden is None:
        txn.record(PlaceSearchedBare(txn.run(), place.id))
    elif txn.roll(_search_odds(txn.needs()), "search", place.id):
        txn.record(ItemFound(hidden.id, place.id, content.item(hidden.kind).name))
    return reports


def _search_odds(needs: Needs) -> Odds:
    """A search's odds, read from the needs as they stand when the search ends."""
    tired = level(Need.FATIGUE, needs.fatigue)
    if tired >= 3:
        return Odds(_SEARCH_BASE, (_SEARCH_EXHAUSTED,))
    if tired == 2:
        return Odds(_SEARCH_BASE, (_SEARCH_VERY_TIRED,))
    return Odds(_SEARCH_BASE)


def _pass(txn: Txn, ticks: int, activity: Activity, *, interruptible: bool) -> tuple[Report, ...]:
    """Let TICKS ticks pass for ACTIVITY, one at a time. This is the scheduler (design §6): every time-driven system
    takes its turn each tick, in a fixed order. Needs are the only system so far; the hazard clocks (M4) and the
    allies (M7) take their turns in this loop too. A need getting worse is reported as it happens, and stops an
    interruptible action with ticks left, so the player can react; a need coming back down to 0 is reported too, but
    only getting worse stops anything."""
    assert ticks > 0, "an action takes at least one tick"
    start = txn.tick()
    pc = txn.pc()
    needs = txn.needs()
    reports: list[Report] = []
    passed = 0
    for _ in range(ticks):
        stepped = tick(needs, activity)
        passed += 1
        worsened = False
        for need in Need:  # within a tick, the needs that got worse come first, then the needs met
            now = level(need, stepped.count(need))
            if now > level(need, needs.count(need)):
                reports.append(NeedWorsened(need, now))
                worsened = True
        reports.extend(NeedMet(need) for need in Need if needs.count(need) > 0 and stepped.count(need) == 0)
        needs = stepped
        if worsened and interruptible and passed < ticks:
            reports.append(Interrupted(activity))
            break
    txn.record(TimePassed(start, Tick(start + passed), activity))
    txn.record(NeedsChanged(pc, needs.thirst, needs.hunger, needs.fatigue))
    return tuple(reports)


def _look(view: View, content: Content) -> LookReport:
    """What a clone sees when it looks, arrives somewhere, or wakes: the place, what lies in the open there, and
    the paths out."""
    place = view.pc_place()
    stacks = _stacked(view.items_at(place.id), content)
    return LookReport(place.name, place.description, stacks, view.exits(place.id))


def _stacked(items: tuple[Item, ...], content: Content) -> tuple[ItemStack, ...]:
    """Items counted into one stack per kind, in items.toml order: how `look` lists a place and `inventory` a
    clone's hands."""
    counts: Counter[ItemKind] = Counter(item.kind for item in items)
    order = {kind: n for n, kind in enumerate(content.items)}  # items.toml order, for stacking
    return tuple(
        ItemStack(content.item(kind).name, content.item(kind).plural, count)
        for kind, count in sorted(counts.items(), key=lambda pair: order[pair[0]])
    )


def _meant(words: tuple[str, ...], pool: tuple[Item, ...], content: Content) -> tuple[Item, ...] | WhichOne | None:
    """The items in POOL that WORDS mean. A kind answers when every word is a word of its name or of its plural.
    One kind answering means its items — all of them when the words answer only to the plural ("take bars"),
    otherwise just the one with the lowest ID — and more than one kind answering is a question for the player.
    The words arrive lowercased, with any leading article already dropped by the parser."""
    order = {kind: n for n, kind in enumerate(content.items)}  # items.toml order, for WhichOne
    answering: list[tuple[ItemKind, bool]] = []
    for kind in sorted({item.kind for item in pool}, key=order.__getitem__):
        by_name = all(word in content.item(kind).name.split() for word in words)
        by_plural = all(word in content.item(kind).plural.split() for word in words)
        if by_name or by_plural:
            answering.append((kind, by_name))
    if not answering:
        return None
    if len(answering) > 1:
        return WhichOne(tuple(content.item(kind).name for kind, _ in answering))
    kind, by_name = answering[0]
    of_kind = tuple(item for item in pool if item.kind == kind)  # the pool is in ID order
    return of_kind[:1] if by_name else of_kind


def _handle(txn: Txn, content: Content, items: tuple[Item, ...], *, taking: bool) -> tuple[Report, ...]:
    """Move ITEMS between the open where the PC stands and its hands — taking them up, or with TAKING false
    putting them down — as one tick of handling, each item in ID order."""
    place = txn.pc_place().id
    pc = txn.pc()
    reports = _pass(txn, 1, Activity.HANDLING, interruptible=False)
    for item in items:
        name = content.item(item.kind).name
        fact = ItemTaken(pc, item.id, place, name) if taking else ItemDropped(pc, item.id, place, name)
        txn.record(fact)
    return reports


# Definition order is the order routes break ties in.
_WAYS = tuple(Direction)


def _route_home(view: View) -> Route | None:
    """The PC's route home over known ground, meaning paths between two visited places: a clone can't be sent over
    ground nobody has walked. Shortest by total ticks; among equally short ones, the route whose steps come first
    in `Direction` order, step by step, which is what Dijkstra over the priority `(ticks, steps)` finds. Every edge
    adds ticks and lengthens the steps, so a popped node's route can't be improved on later."""
    start = view.pc_place().id
    home = view.home().id
    if start == home:
        return Route((), 0)
    known = frozenset(view.visited())
    step_of = {way: n for n, way in enumerate(_WAYS)}
    walked: set[NodeId] = set()
    frontier: list[tuple[int, tuple[int, ...], NodeId]] = [(0, (), start)]
    while frontier:
        ticks, steps, node = heapq.heappop(frontier)
        if node == home:
            return Route(tuple(_WAYS[n] for n in steps), ticks)
        if node in walked:
            continue  # a better route here was already expanded
        walked.add(node)
        for out in view.exits(node):
            if out.to in known:
                heapq.heappush(frontier, (ticks + out.ticks, (*steps, step_of[out.direction]), out.to))
    return None
