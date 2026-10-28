# First slice: decisions and build order

The working plan for the first build (design §14). `docs/design.md` is the vision; this file records the decisions
that make it buildable and the order we build in. The orchestrating agent keeps it current: decisions change here
first, and §16 of the design doc carries a one-line summary of each answer.

Everything below was decided on 2026-10-27 unless marked *proposed*: those are the orchestrator's defaults, open to
change.

## Scope

- **Engine first, then the LLM.** The slice is played with typed engine commands and template text until it works end
  to end; the intent parser and narrator are the last milestone. The model-free path stays for replay tests.
- **One game with clean seams** (§16 Q2). No lore-pack machinery; the setting's content lives in this repo.
- **Content is TOML** (§16 Q3), read with stdlib `tomllib` and validated into frozen dataclasses at startup. Bad
  content fails loudly. It lives in `src/vat_born/content/`.
- **Python** (§16 Q1).

## Time and actions

- **A tick is 10 minutes**, so a day is 144 ticks. The phases are morning 06–12, afternoon 12–18, evening 18–22,
  and night 22–06, and day 1 starts at 06:00. A game day runs from 06:00 to 06:00, so a night belongs to the day it
  began in.
- **Free actions take no time and are unlimited:** `look`, `examine`, `inventory`, `map`, `status`, `where`, and the
  log. They describe only what the PC knows. Every other action costs at least one tick.
- **The player sees the day, the phase, and plain durations** ("Day 3, evening", "about an hour"), never raw ticks.
- **An interrupted long action keeps its progress where that's natural.** Building and crafting store progress on
  the thing being made; travel stops where you are; rest recovers in proportion to the time spent; an interrupted
  search finds nothing.
- **Search draws from a finite hidden pool** per place, seeded at worldgen. Each search rolls to reveal the next
  thing, and an empty pool says so.

## Danger

- **Hazard clocks** roll every tick against a chance derived from a daily rate that rises over the days, with a hard
  ceiling: the threat comes by day N at the latest. Telegraph stages escalate before the lethal stage is possible.
  The slice has two:
  - **a predator** stalking the decks (tracks, a kill site, sounds at night, then an attack);
  - **air recycler failure**, which forces repairs and building.
- **Visibility:** each stage shows up as a sign in the world, and the current odds appear in `status` and before
  risky actions.
- **Confirmation** only for actions that can kill the PC or can't be undone, with the odds in the prompt.
- **A fight is one roll.** `fight` shows the odds and the stakes first, then resolves: win, wounded, flee, or die.

## Death and continuity

- **Permadeath with bones** (design §4): the body stays where it fell, with its kit, and its killer, or at least a
  raised local hazard, stays too.
- **The world moves on** for a seeded 1–3 days before the next vat wakes: clocks advance, allies roll their jobs, and
  the body decays. The new clone gets a short "while you were gone" report.
- **A new clone knows places, not details.** The explored map carries over; items, people, and hazards must be
  rediscovered.

## Base

- **Four rooms:** vat bay, workshop, store, and bulkhead. Each has upgrade levels, built as long actions with saved
  progress:
  - the bulkhead lowers the predator clock;
  - the store cuts spoilage and scent exposure;
  - the workshop unlocks recipes and speeds crafting;
  - the vat bay improves waking (details in M6).

## People and content

- **PC needs:** hydration, calories, fatigue, and injuries. Morale waits until allies and the narrator can drive it.
- **No skills in the slice.** Odds modifiers come from tools, conditions, needs, and injuries. Skills that improve
  with use (§8.1) wait until the playtest shows whether the loop needs them.
- **Allies follow standing orders unless a need or their own goal wins out**, and the engine decides refusals and
  desertion (§8.2). In the slice, allies come only from other vats (§16 Q18).
- **The faction is a wary scavenger clan.** Neutral at first, they trade, compete for the same salvage, and can tip
  either way. No language barrier yet.
- **Set pieces:** the first predator sighting (crossing a threshold region: a glimpse, not a fight) and first contact
  with the scavengers (they find you).
- **Worldgen takes only a seed** (§16 Q8).

## How the engine is driven

- `vat-born [--seed N] [--world PATH]` plays one persistent world, stored in a SQLite file that is created on first
  use. `--world` names the file. Without it, worlds live in the user data directory, one per seed (§3.2): `--seed N`
  opens world N, and with neither flag the last world played resumes, or a new one starts with a random seed.
- Commands arrive one per line on stdin, from a terminal or a pipe, and end of input exits cleanly.
- Agents and tests always pass `--world` with a scratch path, so they never touch the player's worlds or each
  other's. Agents play interactively through zmx (see AGENTS.md).
- Every roll and state change lands in the append-only event log, so the same seed and the same commands produce
  the same log.

## Invariants in code

M0 built the engine invariants from AGENTS.md into the engine's structure, so a worker can't break one by missing a
sentence:

- **Randomness comes from named streams.** Every draw comes from a stream keyed by what it is for (seed, purpose,
  tick, subject), never from one shared generator. A new roll in one system then doesn't shift every later roll on
  the seed, a resumed world needs no saved generator state, and transcripts change only where behavior did. The
  `random` module and the wall clock are lint errors everywhere but `dice.py`.
- **Every chance is rolled against odds:** a base rate plus named modifiers. Each roll is logged with its
  breakdown, so the log and the player see the same numbers. The one exception (*proposed* with M4): a hazard
  clock rolls every tick, and logging each miss would bury the log, so only a roll that fires is logged, in the
  fact it causes. Its draws still come from a stream keyed by the clock and the tick.
- **State changes only by recording a fact,** which applies it and appends it to the log in one step, so the log
  can't miss a change. The schema keeps the log append-only: triggers reject updates and deletes.
- **Free actions get a read-only view** of the world, and SQLite refuses writes outside a timed action's
  transaction, so free actions can't change state or create knowledge.

## Testing

The orchestrator is also the integration tester (decided 2026-10-27). There are no unit tests.

- **Scenarios are transcripts.** Each file in `tests/scenarios/` holds a seed, a line saying what it covers, and a
  session: each command, then the text the player saw and the events it logged (`vat-born --show-log`).
  `uv run pytest` replays every scenario in a fresh scratch world and compares; `uv run pytest --regen` rewrites the
  files when a change is meant to alter them, so review reads behavior changes as transcript diffs. Only scenarios
  about worldgen include the log of making the world (`# show-log: all`), so a worldgen change leaves the rest
  alone.
- **Each scenario also replays under a different hash seed, and split across two processes** (stop halfway, then
  resume). Both must give the same transcript, which catches set-order bugs and state that isn't saved.
- **A crash sweep** plays many seeds for a few in-game days and checks only that nothing crashes, the engine's own
  assertions included.
- **Every commit runs the suite** through the pre-commit hook, so the suite has to stay fast.
- **The orchestrator writes the scenarios,** usually as a task's acceptance criteria. Workers regenerate the
  transcripts their change is meant to alter and list each one in their report. They don't add, delete, or
  hand-edit scenarios unless the task says to.

## Milestones

- **M0 Skeleton** (written by the orchestrator; workers build on it):
  - package layout and core types: IDs, ticks and game time, events, commands and intents;
  - the world seed and the dice (see Invariants in code), with AGENTS.md and the lint messages updated to match;
  - the SQLite schema, data access, and the append-only event log;
  - the TOML content loader;
  - the REPL (stdin line → command parser → engine → events → text), with `--seed` and `--world`;
  - `status` and `where` as the first free actions;
  - the transcript harness and the first scenarios, replacing the placeholder `tests/test_cli.py`, with the suite
    added to the pre-commit hook.
- **M1 World:** worldgen for the decks layer (region graph, vat-bay spawn), timed movement, `look`, `map`, and
  `where`, with exits in a fixed order ("Paths: north to …"). Decided 2026-10-27:
  - directions are compass words: north, south, east, west, up, and down (n, s, e, w, u, d);
  - the home section is fixed content, the same on every seed: the vat bay with the workshop, the store, and the
    bulkhead around it, the rooms M6 turns into the base;
  - beyond the bulkhead, worldgen lays a corridor, one segment per frame of the hull, with side rooms off it and one
    ladder down to a lower deck: 20–30 places in all, a few hours' walk end to end. Content tables hold the places;
    the seed picks which appear, where, and how long each walk is. Later milestones place their own things (search
    pools, the predator's lair, the scavengers, the captain's door) on this map;
  - the bulkhead stands open from the start; shutting and reinforcing it is M6's upgrade.
- **M2 Time and needs:** the scheduler, interruptible long actions, the PC's needs, and the actions that answer them
  (drink, rest). Decided 2026-10-27:
  - the needs are thirst, hunger, and fatigue (injuries come with fighting, in M4). Each counts the ticks since it
    was last answered and reads as a level: thirsty after 12 hours, very thirsty after a day, dying of thirst
    after two; hungry after a day, very hungry after three, starving after a week; tired after 16 hours awake, very
    tired after a day, exhausted after a day and a half. What comes after the last level waits for death (M5);
  - water comes from a tap in the vat bay, so home is where you drink; `eat` moves to M3, where food is found;
  - resting brings fatigue down twice as fast as being awake builds it;
  - the scheduler is a tick loop: a timed action runs tick by tick, and every time-driven system (needs now, the
    hazard clocks in M4, allies in M7) takes its turn each tick in a fixed order. A need getting worse stops a
    long wait or rest. A priority queue can replace the loop if sparse events ever need one.
- **M3 Search and items:** hidden pools, `search`, items and inventory, eating what you find, and explicit odds with
  their breakdown. Decided 2026-10-27:
  - items are content: a ration bar and a tin of stew (a meal each, answering a day's hunger), a handful of pale
    shoots (a snack, half a day's), a canteen (two drinks, filled at water), and a hand lamp (+15% to searches while
    carried). Salvage waits for building (M6);
  - each kind of place can hide a few things, drawn per place at worldgen from a table for that kind: food in the
    galley and hydroponics, a canteen in the crew quarters and the pump room, a lamp in the machine shop. The
    storeroom at home always hides one ration bar;
  - `search` takes an hour and rolls to turn up the next hidden thing: 50%, −10% very tired, −20% exhausted, +15%
    with a lamp, shown with the roll. An interrupted search finds nothing. Searching a place with nothing left says
    so, and then the clone knows: searching there again is refused at no cost. That knowledge is the clone's, not
    the world's, so a new clone must search again;
  - found things lie where they were found until taken, and `look` lists them. `take`, `take all`, and `drop` take
    ten minutes; `inventory` is free. No carrying limit yet;
  - `eat` eats food you carry, in ten minutes. `fill` fills your canteens at water, and `drink` away from water
    drinks from a canteen;
  - items answer to any of their words: "take bar", "eat stew".
- **M4 Danger:** both hazard clocks with their telegraphs, odds in `status`, confirmations, `fight`, and injuries.
  *Proposed* 2026-10-27, the orchestrator's defaults, built while the designer was away:
  - each clock has four stages: three signs, then its threat. Every tick it may roll to reach the next stage, at a
    daily chance that starts low and rises each day, but never more than one stage a day, and each stage comes by a
    set day whatever the rolls. The predator starts at 30% a day, rising 10 points a day to 80%, and hunts by day 9
    at the latest; the air recycler starts at 10%, rising 5 points a day to 50%, and fails by day 10;
  - **the predator** leaves tracks in a corridor, then a kill in a side room, then cries out at midnight, then
    hunts. Hunting, it can attack anywhere: 40% a day out on the decks, 10% at home, 20 points more at night;
  - **the air recycler**, the hum behind the vat bay, stutters, then the air goes stale, then a warning light comes
    on, all in the vat bay. Then it fails, and the home section's air goes bad: a new need, breath, builds there
    (short of breath after an hour, gasping after three, suffocating after five, dead after six) and eases out on
    the decks. `repair` at the vat bay fixes it, two hours' work for each stage it has reached, kept when
    interrupted, and the clock starts over;
  - a clone learns of a clock from its signs. `status` lists each clock it knows of, by the worst sign it has seen,
    with today's odds that it grows worse, or for a hunting predator the odds of an attack where you are;
  - an attack stops whatever you're doing, and then it's `fight` or `flee`; nothing else will do. Both ask first,
    with their odds. A fight rolls to drive the predator off (35%), which sends its clock back to quiet; failing
    that, it rolls to survive wounded (70%), and the predator retreats to its cries. Fleeing rolls to get back to
    where you came from, unhurt (50%), and failing that, the same roll to survive. Being very tired or exhausted
    costs 10 or 20 points on all three, and so does each level of wounds;
  - a fight is two rolls, not one as first planned: drive it off, then survive. Each is an ordinary roll with its
    odds shown, so the log and the player see the same numbers;
  - wounds: wounded, then badly wounded, and a third wound kills. A wound heals in a day and a half awake, or half a
    day resting, and also costs 10 points a level on searches;
  - death ends the run, with its cause. Until M5 builds what follows, a dead clone can only quit.
- **M5 Death:** permadeath, bones, the respawn gap and its report, and clone knowledge. *Proposed* 2026-10-27, the
  orchestrator's defaults:
  - needs kill at last: thirst after three days without a drink, hunger after two weeks without food. Fatigue
    never kills; exhausted just keeps costing odds;
  - the body stays where it fell, with everything it carried lying around it, and `look` shows it: "The body of
    clone 1 lies here", then only bones after a few days. Killed by the predator, the predator keeps hunting;
  - the next clone wakes in the vat bay after a seeded one to three days, in the same turn as the death. The
    world runs through the gap tick by tick: the clocks climb and leave their signs, with nobody there to see
    them. A short report says who died, where, of what, and how long ago;
  - the new clone keeps the map (the places visited); what was searched bare and which signs were seen it must
    learn again, and it starts with fresh needs and no wounds.
- **Playtest:** the designer plays the death-and-respawn loop on one seed, with template text. This is the §14
  success test, run early on purpose: if the loop isn't fun, we change course before building M6–M9.
- **M6 Base:** the four rooms, construction with saved progress, and upgrades with their effects on the clocks.
- **M7 People:** one ally from another vat (orders, needs, jobs, reports), the scavenger faction, and both set pieces.
- **M8 End of the slice:** the locked captain's-seat door.
- **M9 LLM:** the intent parser (free text to schema-validated intents) and the narrator (resolved outcomes to
  prose), with the model-free path kept for tests.
- Then the success test (§14) again, on the whole slice with the narrator: is a death-and-respawn loop on one seed
  fun as text alone?

Status: M0 to M4 done (2026-10-28): the generated decks, walking, `look`, `map`, `where` with the way home, needs
on a tick loop, drinking at the tap, resting, hidden finds and searching with visible odds, carrying, eating, the
canteen, the lamp, and both hazard clocks with their signs, the predator's attacks, fighting and fleeing with
confirmed odds, wounds, the failing air, and repairs. M4 was built on the proposed defaults above, which are still
the designer's to confirm. Next: M5.

## Running the work

- **Orchestrator** (Claude Code): plans, writes task specs and their scenarios, owns the architecture, integration,
  and tests, reviews and merges, and keeps this file current.
- **Workers:** GLM 5.3, started with `scripts/worker <task> <spec>`: one task per worktree (`.worktrees/<task>`,
  branch `pi/<task>`), committed through the pre-commit hook. Calibration is done, so two or three run in parallel on
  tasks that touch different files. A spec gives the change and its acceptance transcripts exactly, and code only
  where an invariant is tricky; AGENTS.md's Workers section covers the standing rules.
- **Review before merge:** rerun the check and the tests, read the diff (new suppressions, `cast(`, edits to config
  or `tests/`) and every changed transcript, and play the change through zmx. At most three rounds of fixes; after
  two failed rounds, escalate to a stronger model or do the task directly.
- **Merging:** `scripts/land <task> < message` squash-merges into `main` with a message naming the task and the
  worker run, pushes, and removes the worktree. The run ID finds the spec and the session in pi-worker's run log.
- **Budget:** the Z.ai Silver plan allows 12K credits per 5 hours and 60K per week. Calibration measured about 55
  credits for a small task (`look`: 3 minutes, 23 turns) and 290 for a medium one (paths and walking: 13 minutes, 52
  turns), roughly 40 medium tasks per 5 hours, so the limits are far off. Both tasks came back right from precise
  specs. `or-glm` (OpenRouter, pay per token) is the overflow.
