"""Events into the words a player reads. This is template text until the narrator arrives (M9); the scenario
transcripts pin it down."""

from typing import assert_never

from vat_born.clock import TICKS_PER_DAY, TICKS_PER_HOUR, GameTime
from vat_born.dice import Odds
from vat_born.events import (
    Ate,
    Attacked,
    ClockAdvanced,
    ClockStarted,
    CloneWoke,
    Cornered,
    Danger,
    Dead,
    DrankFrom,
    Event,
    FightStakes,
    FleeStakes,
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
    NothingToFight,
    NothingToFill,
    NothingToFlee,
    NotTired,
    NoWater,
    NowhereLeft,
    PathAdded,
    PcDied,
    PcEscaped,
    PcMoved,
    PcWounded,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    PlaceSearchedBare,
    PlaceVisited,
    PredatorAttacked,
    PredatorDrivenOff,
    PredatorRetreated,
    Resumed,
    Rolled,
    Route,
    SignLeft,
    SignNoticed,
    SignSeen,
    StatusReport,
    TimePassed,
    WhichOne,
    WorldCreated,
    Wounded,
    WoundsChanged,
    WoundsHealed,
)
from vat_born.hazards import Clock
from vat_born.needs import Activity, Need
from vat_born.world import Direction, Exit

_NUMBERS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_MINUTES = ("ten minutes", "twenty minutes", "half an hour", "forty minutes", "fifty minutes")

# What each need says as it reaches each level (1 to 3), and how `status` names it there.
_WORSENING = {
    Need.THIRST: ("You're getting thirsty.", "You're very thirsty now.", "You're dying of thirst."),
    Need.HUNGER: ("You're getting hungry.", "You're very hungry now.", "You're starving."),
    Need.FATIGUE: ("You're getting tired.", "You're very tired now.", "You're exhausted."),
}
_NAMED = {
    Need.THIRST: ("thirsty", "very thirsty", "dying of thirst"),
    Need.HUNGER: ("hungry", "very hungry", "starving"),
    Need.FATIGUE: ("tired", "very tired", "exhausted"),
}
_WOUNDS = ("wounded", "badly wounded")  # how `status` names each wound level
_MET = {
    Need.THIRST: "Your thirst is gone.",
    Need.HUNGER: "You're no longer hungry.",
    Need.FATIGUE: "You feel rested.",
}

# What each sign says when the clone comes across it, and what `status` calls the danger by its worst sign.
_SIGNS = {
    (Clock.PREDATOR, 1): "Tracks cross the dust here: long, raking marks, too far apart for anything that walks on"
    " two legs.",
    (Clock.PREDATOR, 2): "Something was killed here and eaten where it fell. The bones are cracked open for the"
    " marrow.",
    (Clock.AIR, 1): "Now and then the hum behind the walls stutters, like a missed breath.",
    (Clock.AIR, 2): "The air in here tastes stale and close.",
    (Clock.AIR, 3): "A red warning light pulses above the door.",
}
_DANGERS = {
    (Clock.PREDATOR, 1): "Something big walks the decks.",
    (Clock.PREDATOR, 2): "Something is killing out on the decks.",
    (Clock.PREDATOR, 3): "Something cries on the decks at night.",
    (Clock.PREDATOR, 4): "Something is hunting on the decks.",
    (Clock.AIR, 1): "The air recycler is faltering.",
    (Clock.AIR, 2): "The air at home is going stale.",
    (Clock.AIR, 3): "The air recycler's warning light is on.",
}


def render(event: Event) -> list[str]:
    """The lines to show for EVENT: none for a fact the player doesn't notice."""
    match event:
        case WorldCreated(seed=seed):
            return [f"A new world, seed {seed}."]
        case (
            PlaceAdded()
            | PathAdded()
            | PlaceVisited()
            | ItemHidden()
            | NeedsChanged()
            | WoundsChanged()
            | ClockStarted()
            | ClockAdvanced()
            | SignLeft()
            | SignSeen()
        ):
            return []  # the clocks only show through their signs, and the wounds through their words below
        case CloneWoke(place_name=place):
            return [f"You wake in a clone vat in {place}."]
        case PcMoved(direction=direction, place_name=place):
            return [f"You head {direction} to {place}."]
        case TimePassed():
            return _time_passed(event)
        case Rolled(purpose=purpose, odds=odds, success=success):
            what_for = purpose[:1].upper() + purpose[1:]
            return [f"{what_for} {describe_odds(odds)}: {'success' if success else 'failure'}."]
        case Resumed(seed=seed, run=run, time=time, place_name=place):
            return [f"Seed {seed}, clone {run}. {describe_time(time)}.", f"You are in {place}."]
        case StatusReport(time=time, run=run, levels=levels, wounds=wounds, dangers=dangers):
            return [
                f"{describe_time(time)}. You are clone {run}.",
                _how_you_are(levels, wounds),
                *(_danger(danger) for danger in dangers),
            ]
        case PlaceReport(place_name=place, route=route):
            line = f"You are in {place}."
            match route:
                case None:
                    return [line, "You don't know the way home from here."]
                case Route(steps=steps, ticks=ticks):
                    if not steps:
                        return [line, "You are home."]
                    return [line, f"The way home: {_route(steps)} ({describe_duration(ticks)})."]
        case NoPath(direction=direction):
            return [f"You can't go {direction} from here."]
        case LookReport(place_name=place, description=description, signs=signs, items=items, exits=exits):
            lines = [place[:1].upper() + place[1:], description]
            lines.extend(_SIGNS[sign.clock, sign.stage] for sign in signs)
            if items:
                lines.append(_items_here(items))
            lines.append(_paths(exits))
            return lines
        case MapReport(places=places):
            return [_on_the_map(entry) for entry in places]
        case PhaseChanged(before=before, after=after):
            if after.day == before.day:
                return [f"It is now {after.phase}."]
            return [f"It is now day {after.day}, {after.phase}."]
        case NeedWorsened(need=need, level=level):
            return [_WORSENING[need][level - 1]]
        case NeedMet(need=need):
            return [_MET[need]]
        case NeedEased(need=need, before=before, after=after):
            return _eased(need, before, after)
        case Interrupted(activity=activity):
            return [_stopped(activity)]
        case NoWater():
            return ["There's no water here."]
        case NotTired():
            return ["You aren't tired."]
        case ItemFound(name=name):
            return [f"You find {_a(name)}."]
        case ItemTaken(name=name):
            return [f"You take {_a(name)}."]
        case ItemDropped(name=name):
            return [f"You drop {_a(name)}."]
        case Ate() | ItemFilled() | DrankFrom() | NotFood() | NothingToFill() | NothingToDrink():
            return _consumed(event)
        case InventoryReport(items=items):
            if not items:
                return ["You aren't carrying anything."]
            return [f"You're carrying {_listed([_stack(stack) for stack in items])}."]
        case WhichOne(names=names):
            return [f"Which do you mean: {_listed([f'the {name}' for name in names], conj='or')}?"]
        case NotHere(words=words):
            return [f'You don\'t see "{" ".join(words)}" here.']
        case NotCarried(words=words):
            return [f'You aren\'t carrying "{" ".join(words)}".']
        case NothingHere():
            return ["There's nothing here to take."]
        case NothingCarried():
            return ["You aren't carrying anything."]
        case PlaceSearchedBare():
            return ["You find nothing, and there's nowhere left to look."]
        case NowhereLeft():
            return ["You've searched here already, and there's nowhere left to look."]
        case SignNoticed(clock=clock, stage=stage):
            return [_SIGNS[clock, stage]]
        case (
            HeardCries()
            | PredatorAttacked()
            | PcWounded()
            | Attacked()
            | Cornered()
            | NothingToFight()
            | NothingToFlee()
            | FightStakes()
            | FleeStakes()
            | Wounded()
            | WoundsHealed()
            | PredatorDrivenOff()
            | PredatorRetreated()
            | PcEscaped()
            | PcDied()
            | Dead()
        ):
            return _hunt(event)
        case _:
            assert_never(event)


def describe_time(time: GameTime) -> str:
    return f"Day {time.day}, {time.phase}"


def describe_duration(ticks: int) -> str:
    """A duration as a person would say it: "half an hour", "two hours", "about a day"."""
    assert ticks > 0, "a duration is at least one tick"
    if ticks < TICKS_PER_HOUR:
        return _MINUTES[ticks - 1]
    if ticks < TICKS_PER_DAY:
        hours, rest = divmod(ticks, TICKS_PER_HOUR)
        if rest == 0:
            return _count(hours, "hour")
        if rest * 2 == TICKS_PER_HOUR:
            return "an hour and a half" if hours == 1 else f"{_number(hours)} and a half hours"
        rounded = round(ticks / TICKS_PER_HOUR)
        return "about a day" if rounded == 24 else f"about {_count(rounded, 'hour')}"
    days, rest = divmod(ticks, TICKS_PER_DAY)
    if rest == 0:
        return _count(days, "day")
    return f"about {_count(round(ticks / TICKS_PER_DAY), 'day')}"


def describe_odds(odds: Odds) -> str:
    """The chance and how it was reached: "55% (base 40%, lamp +15%)", or just "40%" when nothing modifies it."""
    if not odds.modifiers:
        return _percent(odds.chance)
    parts = [f"base {_percent(odds.base)}", *(f"{m.reason} {m.delta:+.0%}" for m in odds.modifiers)]
    return f"{_percent(odds.chance)} ({', '.join(parts)})"


def _hunt(
    event: HeardCries
    | PredatorAttacked
    | PcWounded
    | Attacked
    | Cornered
    | NothingToFight
    | NothingToFlee
    | FightStakes
    | FleeStakes
    | Wounded
    | WoundsHealed
    | PredatorDrivenOff
    | PredatorRetreated
    | PcEscaped
    | PcDied
    | Dead,
) -> list[str]:
    """The words for the hunt (M4): the cries, the attack, the gambles and their stakes, the wounds it leaves,
    and the clone's death at its jaws."""
    match event:
        case HeardCries():
            return ["Somewhere out on the decks, something screams: a long, rising cry that ends too suddenly."]
        case PredatorAttacked():
            return []  # the `Attacked` report says it, after the tick's other news
        case Attacked():
            return ["Something huge comes at you out of the dark, all teeth and hooked claws: the predator!"]
        case Cornered():
            return ["The predator is on you. Fight, or flee!"]
        case NothingToFight():
            return ["There's nothing here to fight."]
        case NothingToFlee():
            return ["There's nothing to flee from."]
        case FightStakes(drive_off=drive_off, survive=survive):
            return _stakes("Fight it", "drive it off", drive_off, survive)
        case FleeStakes(get_away=get_away, survive=survive):
            return _stakes("Run for it", "get away", get_away, survive)
        case PcWounded():
            return ["It tears into you."]
        case Wounded(level=level):
            return [f"You're {_WOUNDS[level - 1]}."]
        case WoundsHealed(level=level):
            if level == 0:
                return ["Your wounds have healed."]
            assert level == 1, "wounds only heal down to wounded, or to none"
            return ["Your wounds are healing: you're only wounded now."]
        case PredatorDrivenOff():
            return ["It shrieks and flees into the dark, bleeding. It won't be back for a while."]
        case PredatorRetreated():
            return ["It slinks off into the dark, sated for now."]
        case PcEscaped():
            return ["You tear free and run."]
        case PcDied():
            return ["It drags you down. You are dead."]
        case Dead():
            return ["You are dead. Type quit to stop."]
        case _:
            assert_never(event)


def _consumed(event: Ate | ItemFilled | DrankFrom | NotFood | NothingToFill | NothingToDrink) -> list[str]:
    """The words for eating and drinking what you carry, and the refusals when there's nothing to eat or fill or
    drink from."""
    match event:
        case Ate(name=name):
            return [f"You eat {_a(name)}."]
        case ItemFilled(name=name):
            return [f"You fill {_a(name)}."]
        case DrankFrom(name=name, drinks=drinks):
            if drinks == 0:
                return [f"Your {name} is empty now."]
            left = f"{_number(drinks)} drink{'s' if drinks > 1 else ''} left"
            return [f"Your {name} has {left}."]
        case NotFood(name=name):
            return [f"You can't eat {_a(name)}."]
        case NothingToFill():
            return ["You have nothing that needs filling."]
        case NothingToDrink(name=name):
            return [f"There's no water here, and your {name} is empty."]
        case _:
            assert_never(event)


def _time_passed(event: TimePassed) -> list[str]:
    match event.activity:
        case Activity.WALKING:
            return []  # the move itself says where the walk went
        case Activity.WAITING:
            return [f"You wait {describe_duration(event.end - event.start)}."]
        case Activity.RESTING:
            return [f"You rest {describe_duration(event.end - event.start)}."]
        case Activity.DRINKING:
            return ["You drink your fill."]
        case Activity.SEARCHING:
            return [f"You search for {describe_duration(event.end - event.start)}."]
        case Activity.HANDLING:
            return []  # the item facts say what happened
        case Activity.EATING:
            return []  # the meal says what happened
        case Activity.FIGHTING:
            return []  # the fight's facts say what happened
        case _:
            assert_never(event.activity)


def _stopped(activity: Activity) -> str:
    """What the PC does when an action stops early. A walk or a drink never stops, but the words stay exhaustive."""
    match activity:
        case Activity.WAITING:
            return "You stop waiting."
        case Activity.WALKING:
            return "You stop walking."
        case Activity.RESTING:
            return "You stop resting."
        case Activity.DRINKING:
            return "You stop drinking."
        case Activity.SEARCHING:
            return "You stop searching."
        case Activity.HANDLING:
            return "You stop what you're doing."  # can't happen: handling is never interruptible
        case Activity.EATING:
            return "You stop eating."  # can't happen: eating is never interruptible
        case Activity.FIGHTING:
            return "You stop fighting."  # can't happen: a fight is never interruptible
        case _:
            assert_never(activity)


def _how_you_are(levels: tuple[NeedLevel, ...], wounds: int) -> str:
    """The second line of `status`: each need above level 0, then each wound, named by its level, in `Need` order."""
    words = [_NAMED[entry.need][entry.level - 1] for entry in levels if entry.level > 0]
    if wounds:
        words.append(_WOUNDS[wounds - 1])
    return f"You're {_listed(words)}." if words else "You feel fine."


def _danger(danger: Danger) -> str:
    """A danger line of `status`: the words for its worst sign, with today's chance it grows worse — a hunting
    predator is named by the odds of it striking where the PC is instead."""
    if danger.attack is not None:
        return f"{_DANGERS[danger.clock, danger.stage]} An attack where you are: {describe_odds(danger.attack)} a day."
    return f"{_DANGERS[danger.clock, danger.stage]} It grows worse at {_percent(danger.daily)} a day."


def _stakes(verb: str, win: str, odds: Odds, survive: Odds | None) -> list[str]:
    """What a fight or a flight risks, for the frontend to ask about (design §10.3): the odds of WIN, and of living
    through failing it. SURVIVE None means failing kills outright: a badly wounded clone has no third wound to
    spare, and no roll saves it."""
    otherwise = "you die" if survive is None else f"{describe_odds(survive)} to live through it, wounded"
    return [f"{verb}? {describe_odds(odds)} to {win}; if not, {otherwise}. (yes or no)"]


def _eased(need: Need, before: int, after: int) -> list[str]:
    """What an answered need says, by level: met, eased but not met, or still where it was."""
    if after == before:
        return [] if after == 0 else [f"You're still {_NAMED[need][after - 1]}."]
    if after == 0:
        return [_MET[need]]
    return [f"You're only {_NAMED[need][after - 1]} now."]


def _paths(exits: tuple[Exit, ...]) -> str:
    """The exits as one line, in `Direction` order; only a walk longer than ten minutes says how long it is."""
    return f"Paths: {_exits(exits)}."


def _items_here(items: tuple[ItemStack, ...]) -> str:
    """What lies in the open: "You see two ration bars and a canteen here." """
    return f"You see {_listed([_stack(stack) for stack in items])} here."


def _stack(stack: ItemStack) -> str:
    """Items of one kind, counted: "a ration bar", "two ration bars". A stack that holds water says how full it
    is: "a canteen (full)", "two canteens (empty)", "a canteen (one drink left)"."""
    counted = _a(stack.name) if stack.count == 1 else f"{_number(stack.count)} {stack.plural}"
    return counted if not stack.capacity else f"{counted} ({_how_full(stack)})"


def _how_full(stack: ItemStack) -> str:
    """The state of a stack that holds water, for the brackets after its name."""
    drinks = stack.drinks or 0
    if drinks == stack.capacity:
        return "full"
    if drinks == 0:
        return "empty"
    return f"{_number(drinks)} drink{'s' if drinks > 1 else ''} left"


def _a(name: str) -> str:
    """A name with its article: "a ration bar", "an item"."""
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def _listed(words: list[str], conj: str = "and") -> str:
    """Words joined as a list in a sentence: "a", "a and b", "a, b, and c"; with CONJ "or", "a or b", "a, b, or c"."""
    assert words, "an empty list reads as nothing"
    if len(words) <= 2:
        return f" {conj} ".join(words)
    return f"{', '.join(words[:-1])}, {conj} {words[-1]}"


def _exits(exits: tuple[Exit, ...], *, unknown: bool = False) -> str:
    """The exits as a comma-separated list, in `Direction` order. With UNKNOWN, a way into unvisited ground says so,
    after any duration."""
    if not exits:
        return "none"
    return ", ".join(_exit(out, unknown=unknown) for out in exits)


def _exit(out: Exit, *, unknown: bool) -> str:
    inside = [describe_duration(out.ticks)] if out.ticks > 1 else []
    if unknown and not out.explored:
        inside.append("unexplored")
    way = f"{out.direction} to {out.place_name}"
    return f"{way} ({', '.join(inside)})" if inside else way


def _on_the_map(entry: MapEntry) -> str:
    place = entry.place_name[:1].upper() + entry.place_name[1:]
    here = " (you are here)" if entry.here else ""
    return f"{place}{here}: {_exits(entry.exits, unknown=True)}."


def _route(steps: tuple[Direction, ...]) -> str:
    """The steps as a person would give them: "west, then up, then south five times"."""
    runs: list[tuple[Direction, int]] = []
    for step in steps:
        if runs and runs[-1][0] == step:
            runs[-1] = (step, runs[-1][1] + 1)
        else:
            runs.append((step, 1))
    return ", then ".join(_steps_of_one_way(way, n) for way, n in runs)


def _steps_of_one_way(way: Direction, n: int) -> str:
    if n == 1:
        return str(way)
    if n == 2:
        return f"{way} twice"
    return f"{way} {_number(n)} times"


def _count(n: int, unit: str) -> str:
    """Like "an hour", "two hours", or "a day"."""
    if n == 1:
        return f"{'an' if unit == 'hour' else 'a'} {unit}"
    return f"{_number(n)} {unit}s"


def _number(n: int) -> str:
    return _NUMBERS[n] if n < len(_NUMBERS) else str(n)


def _percent(p: float) -> str:
    # Rounding would show a real chance as 0% or 100%.
    if 0 < p < 0.005:
        return "under 1%"
    if 0.995 < p < 1:
        return "over 99%"
    return f"{p:.0%}"
