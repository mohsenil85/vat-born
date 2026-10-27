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
  content fails loudly. *Proposed:* it lives in `src/vat_born/content/`.
- **Python** (§16 Q1).

## Time and actions

- **A tick is 10 minutes**, so a day is 144 ticks. *Proposed:* the phases are morning 06–12, afternoon 12–18, evening
  18–22, and night 22–06, and day 1 starts at 06:00.
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
- **Allies follow standing orders unless a need or their own goal wins out**, and the engine decides refusals and
  desertion (§8.2). *Proposed:* in the slice, allies come only from other vats (§16 Q18).
- **The faction is a wary scavenger clan.** Neutral at first, they trade, compete for the same salvage, and can tip
  either way. *Proposed:* no language barrier yet.
- **Set pieces:** the first predator sighting (crossing a threshold region: a glimpse, not a fight) and first contact
  with the scavengers (they find you).
- *Proposed:* **worldgen takes only a seed** (§16 Q8).

## How the engine is driven

*Proposed, and shared with the integration-test effort:*

- `vat-born [--seed N] [--world PATH]` starts or resumes the world stored in the SQLite file at `PATH`, by default
  one file per seed under the user data directory. A new world without `--seed` gets a random one.
- Commands arrive one per line on stdin, from a terminal or a pipe, and end of input exits cleanly. Agents play
  interactively through zmx (see AGENTS.md).
- Every roll and state change lands in the append-only event log, so the same seed and the same commands produce
  the same log. Replay tests assert on that log.

## Milestones

- **M0 Skeleton** (written by the orchestrator; workers build on it):
  - package layout and core types: IDs, ticks and game time, events, commands and intents;
  - the world seed and the `random.Random` passed through the engine;
  - the SQLite schema, data access, and the append-only event log;
  - the TOML content loader;
  - the REPL (stdin line → command parser → engine → events → text), with `--seed` and `--world`;
  - `status` and `where` as the first free actions, with deterministic replay.
- **M1 World:** worldgen for the decks layer (region graph, vat-bay spawn), timed movement, `look`, `map`, and
  `where`, with exits in a fixed order ("Paths: north to …").
- **M2 Time and needs:** the scheduler, interruptible long actions, the PC's needs, and the actions that answer them
  (eat, drink, rest).
- **M3 Search and items:** hidden pools, `search`, items and inventory, and explicit odds with their breakdown.
- **M4 Danger:** both hazard clocks with their telegraphs, odds in `status`, confirmations, `fight`, and injuries.
- **M5 Death:** permadeath, bones, the respawn gap and its report, and clone knowledge.
- **M6 Base:** the four rooms, construction with saved progress, and upgrades with their effects on the clocks.
- **M7 People:** one ally from another vat (orders, needs, jobs, reports), the scavenger faction, and both set pieces.
- **M8 End of the slice:** the locked captain's-seat door.
- **M9 LLM:** the intent parser (free text to schema-validated intents) and the narrator (resolved outcomes to
  prose), with the model-free path kept for tests.
- Then the success test (§14): is a death-and-respawn loop on one seed fun as text alone?

Status: M0 not started.

## Running the work

- **Orchestrator** (Claude Code): plans, writes task specs, owns the architecture and integration, reviews and
  merges, and keeps this file current.
- **Workers:** GLM 5.3 through `pi-worker -b glm`, one task per worktree (`.worktrees/<task>`, branch `pi/<task>`),
  committed through the pre-commit hook. The first two or three tasks run one at a time to calibrate; after that, two
  or three run in parallel on independent units.
- **Review before merge:** rerun the check, read the diff (new suppressions, `cast(`, edits to config or `tests/`),
  and play the change through zmx. At most three rounds of fixes; after two failed rounds, escalate to a stronger
  model or do the task directly.
- **Merging:** squash into `main` with a message naming the task and the worker run, and push after each chunk of
  work.
- **Budget:** the Z.ai Silver plan allows 12K credits per 5 hours and 60K per week. Credits per task get measured
  during calibration. `or-glm` (OpenRouter, pay per token) is the overflow.
