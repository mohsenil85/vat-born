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
    Ate,
    ClockAdvanced,
    ClockStarted,
    CloneWoke,
    Danger,
    DrankFrom,
    Event,
    Fact,
    HeardCries,
    Interrupted,
    InventoryReport,
    ItemDropped,
    ItemFilled,
    ItemFound,
    ItemHidden,
    ItemStack,
    ItemTaken,
    LookReport,
    MapEntry,
    MapReport,
    NeedEased,
    NeedLevel,
    NeedMet,
    NeedsChanged,
    NeedWorsened,
    NoPath,
    NotCarried,
    NotFood,
    NotHere,
    NothingCarried,
    NothingHere,
    NothingToDrink,
    NothingToFill,
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
    Sign,
    SignLeft,
    SignNoticed,
    SignSeen,
    StatusReport,
    TimePassed,
    WhichOne,
    WorldCreated,
)
from vat_born.hazards import Clock, daily_chance, due, is_midnight, may_move, tick_chance
from vat_born.intents import (
    Drink,
    Drop,
    DropAll,
    Eat,
    Fill,
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
from vat_born.store import ClockState, LogEntry, Store, Txn, View, WorldError
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
                for clock in Clock:
                    txn.record(ClockStarted(clock))
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
                | Fill()
                | Search()
                | Rest()
                | RestUntil()
                | Take()
                | TakeAll()
                | Drop()
                | DropAll()
                | Eat()
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
            day = game_time(view.tick()).day
            dangers = tuple(
                Danger(clock, worst, daily_chance(clock, day))
                for clock in Clock
                if (worst := max((sign.stage for sign in view.signs_seen() if sign.clock is clock), default=None))
            )
            return (StatusReport(game_time(view.tick()), view.run(), levels, dangers),)
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
            return _pass(txn, ticks, content, Activity.WAITING, interruptible=True)
        case WaitUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), content, Activity.WAITING, interruptible=True)
        case Move(direction=direction):
            place = txn.pc_place()
            way = next((out for out in txn.exits(place.id) if out.direction == direction), None)
            if way is None:
                return (NoPath(direction),)
            reports = _pass(txn, way.ticks, content, Activity.WALKING, interruptible=False)
            txn.record(PcMoved(txn.pc(), place.id, way.to, direction, way.place_name))
            if not txn.is_visited(way.to):
                txn.record(PlaceVisited(way.to))
            seen = set(txn.signs_seen())
            for sign in txn.signs_at(way.to):  # the arrival comes across every sign there the clone hasn't seen
                if sign not in seen:
                    txn.record(SignSeen(txn.run(), sign.clock, sign.stage))
            return (*reports, _look(txn, content))
        case Drink():
            return _drink(txn, content)
        case Fill():
            return _fill(txn, content)
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
        case Eat(words=words):
            match _meant(words, txn.carried(), content):
                case None:
                    return (NotCarried(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _eat(txn, content, items[0])  # eating is always one item: the lowest ID
        case Rest(ticks=ticks):
            if ticks is None:  # until rested
                fatigue = txn.needs().fatigue
                if fatigue == 0:
                    return (NotTired(),)
                ticks = (fatigue + 1) // 2  # just long enough to reach 0
            return _pass(txn, ticks, content, Activity.RESTING, interruptible=True)
        case RestUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), content, Activity.RESTING, interruptible=True)
        case _:
            assert_never(intent)


# A search takes an hour, and rolls to turn up the next hidden thing: 50%, plus the points of everything carried
# that helps a search, less when fatigue clouds the search.
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
    reports = _pass(txn, _SEARCH_TICKS, content, Activity.SEARCHING, interruptible=True)
    if txn.tick() - start < _SEARCH_TICKS:  # a need stopped the search early, and an interrupted search finds nothing
        return reports
    hidden = txn.next_hidden(place.id)
    if hidden is None:
        txn.record(PlaceSearchedBare(txn.run(), place.id))
    elif txn.roll(_search_odds(txn, content), "search", place.id):
        txn.record(ItemFound(hidden.id, place.id, content.item(hidden.kind).name))
    return reports


def _search_odds(txn: Txn, content: Content) -> Odds:
    """A search's odds, read from what the PC carries and the needs as they stand when the search ends. Each kind
    of thing carried that helps a search adds its points, however many of it are carried."""
    modifiers = [
        Modifier(defn.name, defn.search / 100)
        for kind in _kinds_carried(txn, content)
        if (defn := content.item(kind)).search
    ]
    tired = level(Need.FATIGUE, txn.needs().fatigue)
    if tired >= 3:
        modifiers.append(_SEARCH_EXHAUSTED)
    elif tired == 2:
        modifiers.append(_SEARCH_VERY_TIRED)
    return Odds(_SEARCH_BASE, tuple(modifiers))


def _kinds_carried(txn: Txn, content: Content) -> tuple[ItemKind, ...]:
    """The kinds of thing the PC carries, in items.toml order."""
    order = {kind: n for n, kind in enumerate(content.items)}
    return tuple(sorted({item.kind for item in txn.carried()}, key=order.__getitem__))


@dataclass(slots=True)
class _Hazards:
    """The hazard clocks' side of one action's ticks: each clock as the ticks find it, the signs this clone has come
    across, and the facts to record once the ticks are done. The rolls that decide a move come from the keyed
    streams, not logged rolls — the exception to every roll being logged (hazards.py)."""

    txn: Txn
    content: Content
    run: int
    here: NodeId
    clocks: dict[Clock, ClockState]
    seen: set[Sign]
    facts: list[Fact]

    def turn(self, at: Tick, reports: list[Report]) -> bool:
        """Each clock's turn at tick AT, in `Clock` order: it may move up a stage and leave its sign, which the clone
        notices if it is left right where the clone is, and the cries carry at midnight once the predator is far
        enough along. Returns whether something happened the player can react to."""
        stopped = False
        for clock in Clock:
            state = self.clocks[clock]
            standing = state
            if may_move(state.stage, state.since, at):
                day = game_time(at).day
                daily = daily_chance(clock, day)
                certain = due(clock, state.stage + 1, at)
                if certain or self.txn.stream("clock", clock, at).random() < tick_chance(daily):
                    stage = state.stage + 1
                    standing = ClockState(clock, stage, at)
                    self.facts.append(ClockAdvanced(clock, stage, at, daily, certain))
                    if stage < 4:  # the threat (stage 4) leaves no sign
                        place = _sign_place(self.txn, self.content, clock, stage, at)
                        self.facts.append(SignLeft(clock, stage, place, at))
                        sign = Sign(clock, stage)
                        if place == self.here and sign not in self.seen:
                            self.facts.append(SignSeen(self.run, clock, stage))
                            self.seen.add(sign)
                            reports.append(SignNoticed(clock, stage))
                            stopped = True
            if clock is Clock.PREDATOR and is_midnight(at) and standing.stage >= 3:
                reports.append(HeardCries())
                cries = Sign(Clock.PREDATOR, 3)
                if cries not in self.seen:  # the first time a clone hears them is its coming across them
                    self.facts.append(SignSeen(self.run, Clock.PREDATOR, 3))
                    self.seen.add(cries)
                stopped = True
            self.clocks[clock] = standing
        return stopped


def _pass(txn: Txn, ticks: int, content: Content, activity: Activity, *, interruptible: bool) -> tuple[Report, ...]:
    """Let TICKS ticks pass for ACTIVITY, one at a time. This is the scheduler (design §6): every time-driven system
    takes its turn each tick, in a fixed order: the needs, then the hazard clocks (design §7.2). A need getting worse,
    or a sign coming to the clone's notice, is reported as it happens and stops an interruptible action with ticks
    left, so the player can react; a need coming back down to 0 is reported too, but only getting worse and the
    clocks stop anything. The clocks' facts are recorded after the needs', in the order they happened: each advance,
    then the sign it left, then the clone coming across it."""
    assert ticks > 0, "an action takes at least one tick"
    start = txn.tick()
    pc = txn.pc()
    needs = txn.needs()
    hazards = _Hazards(
        txn,
        content,
        txn.run(),
        txn.pc_place().id,
        {state.clock: state for state in txn.clocks()},
        set(txn.signs_seen()),
        [],
    )
    reports: list[Report] = []
    passed = 0
    for _ in range(ticks):
        stepped = tick(needs, activity)
        passed += 1
        at = Tick(start + passed)
        worsened = _needs_turn(needs, stepped, reports)
        noticed = hazards.turn(at, reports)  # every clock takes its turn every tick, whatever the needs did
        stopped = worsened or noticed
        needs = stepped
        if stopped and interruptible and passed < ticks:
            reports.append(Interrupted(activity))
            break
    txn.record(TimePassed(start, Tick(start + passed), activity))
    txn.record(NeedsChanged(pc, needs.thirst, needs.hunger, needs.fatigue))
    for fact in hazards.facts:
        txn.record(fact)
    return tuple(reports)


def _needs_turn(needs: Needs, stepped: Needs, reports: list[Report]) -> bool:
    """The needs' turn in one tick, on the counts after it (STEPPED) against the counts before (NEEDS): the needs that
    got worse are reported first, then the needs met. Returns whether any got worse."""
    worsened = False
    for need in Need:
        now = level(need, stepped.count(need))
        if now > level(need, needs.count(need)):
            reports.append(NeedWorsened(need, now))
            worsened = True
    reports.extend(NeedMet(need) for need in Need if needs.count(need) > 0 and stepped.count(need) == 0)
    return worsened


def _sign_place(txn: Txn, content: Content, clock: Clock, stage: int, at: Tick) -> NodeId | None:
    """Where a clock's stage leaves its sign: the predator's tracks in a corridor and its kill in a room beyond the
    home section, drawn where there's a choice; the air recycler's signs all at the vat bay, where it hums. The
    cries (predator 3) are heard, not placed, so they are nowhere."""
    places = txn.places()
    match clock, stage:
        case Clock.AIR, 1 | 2 | 3:
            return next(entry.place for entry in places if entry.kind == content.home.start)
        case Clock.PREDATOR, 1:
            corridors = tuple(e.place for e in places if e.kind == content.decks.corridor.kind)
            return _sign_choice(txn, clock, stage, at, corridors)
        case Clock.PREDATOR, 2:
            beyond = tuple(
                e.place for e in places if e.kind != content.decks.corridor.kind and e.kind not in content.home.places
            )
            return _sign_choice(txn, clock, stage, at, beyond)
        case Clock.PREDATOR, 3:
            return None
        case _:
            raise AssertionError(f"stage {stage} of {clock} leaves no sign")


def _sign_choice(txn: Txn, clock: Clock, stage: int, at: Tick, candidates: tuple[NodeId, ...]) -> NodeId:
    """Pick one of CANDIDATES, in node ID order, with the clock's stream: the seed chooses where each sign lands."""
    assert candidates, f"nowhere for {clock}'s stage {stage} sign to land"
    return txn.stream("clock", clock, "sign", stage, at).choice(candidates)


def _look(view: View, content: Content) -> LookReport:
    """What a clone sees when it looks, arrives somewhere, or wakes: the place, the signs it carries, what lies in
    the open there, and the paths out."""
    place = view.pc_place()
    stacks = _stacked(view.items_at(place.id), content)
    return LookReport(place.name, place.description, view.signs_at(place.id), stacks, view.exits(place.id))


def _stacked(items: tuple[Item, ...], content: Content) -> tuple[ItemStack, ...]:
    """Items counted into stacks, in items.toml order: how `look` lists a place and `inventory` a clone's hands.
    Things that hold water stack by kind and how full they are, fullest first, so a full canteen and an empty one
    are two stacks."""
    counts: Counter[tuple[ItemKind, int | None]] = Counter()
    for item in items:
        holds_water = _capacity(content, item.kind) > 0
        counts[(item.kind, item.drinks if holds_water else None)] += 1
    order = {kind: n for n, kind in enumerate(content.items)}  # items.toml order, for stacking

    def fullest_first(pair: tuple[tuple[ItemKind, int | None], int]) -> tuple[int, int]:
        (kind, drinks), _count = pair
        return (order[kind], -(drinks or 0))  # within a kind, the fullest stack comes first

    return tuple(
        ItemStack(
            content.item(kind).name,
            content.item(kind).plural,
            count,
            drinks,
            _capacity(content, kind),
        )
        for (kind, drinks), count in sorted(counts.items(), key=fullest_first)
    )


def _capacity(content: Content, kind: ItemKind) -> int:
    """How many drinks a thing of this kind holds when full: 0 when it holds no water."""
    return content.item(kind).drinks


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
    reports = _pass(txn, 1, content, Activity.HANDLING, interruptible=False)
    for item in items:
        name = content.item(item.kind).name
        fact = ItemTaken(pc, item.id, place, name) if taking else ItemDropped(pc, item.id, place, name)
        txn.record(fact)
    return reports


def _drink(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Drink your fill: from the place, where there's water, and elsewhere from the thing carried with the fewest
    drinks left, so a nearly empty one drains before a full one is opened."""
    if txn.pc_place().water:
        return _pass(txn, 1, content, Activity.DRINKING, interruptible=False)
    carried = txn.carried()
    held = [item for item in carried if _capacity(content, item.kind) and item.drinks > 0]
    if held:
        chosen = min(held, key=lambda item: (item.drinks, item.id))
        reports = _pass(txn, 1, content, Activity.DRINKING, interruptible=False)
        txn.record(DrankFrom(chosen.id, content.item(chosen.kind).name, chosen.drinks - 1))
        return reports
    empty = [item for item in carried if _capacity(content, item.kind)]
    if empty:
        return (NothingToDrink(content.item(empty[0].kind).name),)
    return (NoWater(),)


def _fill(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Fill everything carried that holds water and isn't full, as one tick of handling, each item in ID order."""
    if not txn.pc_place().water:
        return (NoWater(),)
    carried = txn.carried()
    fillable = [
        item for item in carried if _capacity(content, item.kind) and item.drinks < _capacity(content, item.kind)
    ]
    if not fillable:
        return (NothingToFill(),)
    reports = _pass(txn, 1, content, Activity.HANDLING, interruptible=False)
    for item in fillable:
        txn.record(ItemFilled(item.id, content.item(item.kind).name, _capacity(content, item.kind)))
    return reports


def _eat(txn: Txn, content: Content, item: Item) -> tuple[Report, ...]:
    """Eat one item: a tick of eating, then the meal off the PC's hunger. Hunger builds through the tick like any
    other; the meal is taken off after it, and what remains of the hunger is said by its level."""
    defn = content.item(item.kind)
    if not defn.meal:
        return (NotFood(defn.name),)
    reports = _pass(txn, 1, content, Activity.EATING, interruptible=False)
    before = txn.needs().hunger
    after = max(before - defn.meal, 0)
    txn.record(Ate(txn.pc(), item.id, defn.name, after))
    return (*reports, NeedEased(Need.HUNGER, level(Need.HUNGER, before), level(Need.HUNGER, after)))


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
