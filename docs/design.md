# Design Doc: Vat-Born (working title)

*An audio/text-first roguelike survival base-builder with an LLM narrator, set in the "space Montana" universe.*

Status: pre-prototype design. Drafted 2026-10-20 from a long design conversation.

---

## 0. How we got here

The idea started as "an LLM dungeon master runs a Cast Away roleplay" and drifted, deliberately:

1. **Cast Away → Robinson Crusoe.** From endurance and loss to accumulation and mastery: inventory the wreck, build, farm, fortify.
2. **Chat DM → harness.** Plain chat can't hold state, roll fairly or keep secrets, so state moved into SQLite and randomness into code.
3. **Agent-in-loop → engine-in-loop.** The LLM stopped being the driver and became a parser and narrator.
4. **Island → the space Montana universe.** A gritty frontier sci-fi setting (RimWorld / Caves of Qud register), aboard a Long Sun-style cylinder colony ship.
5. **DM game → roguelike.** Permadeath, procedural generation, free examination, timed actions, a scheduler.
6. **Scope cuts.** No focus-switching between PCs. No AI-authored engine patches. No zoom layers in the first build. Fortress mode before adventure mode.

What survived the whole way: **code owns truth, the model owns words.**

---

## 1. Design pillars

1. **Code owns truth, the model owns words.** The LLM never decides outcomes, probabilities, deaths or state changes. It turns player text into intents and resolved outcomes into prose.
2. **Fair and legible.** Odds are computed by the engine and shown to the player. Threats are telegraphed before they turn lethal.
3. **Non-visual first.** The text REPL and voice are the primary interface, not a port of something else. Narration *is* the UI.
4. **Persistent, single-timeline world.** Seed plus run counter. Last run wins. No save-scumming, no branching.
5. **Build the game, not the engine.** Design the seams for future layers and modes, but build only the first act.

---

## 2. Setting and premise

- **Universe:** the internal working name ("time elves") deliberately says nothing about the setting. Think of it as **space Montana**: futuristic but gritty frontier, room for zombies, wild animals, strange space things. Tonal touchstones: RimWorld (which itself draws on Firefly's frontier western), Caves of Qud.
- **World:** a huge cylindrical colony / generation ship, borrowing heavily from Gene Wolfe's *Book of the Long Sun*.
- **Spawn:** the player wakes in a **clone vat**. This is the diegetic reason the dungeon keeps receiving new arrivals. Other vats exist and are how other wakers (allies, rivals) enter the world.
- **Long-term arc (deferred):** finding the captain's seat changes the zoom level: ship in a solar system, then landers to planets. See §11.

---

## 3. Architecture

### 3.1 Engine-in-loop

The program owns the main loop. Each player turn:

```
input ──► engine command?  ──yes──► resolve deterministically (no LLM call)
             │ no
             ▼
       LLM: intent parser   ──► structured intent (JSON, schema-validated)
             ▼
       engine: validate, compute odds, roll, apply state diffs, run scheduler
             ▼
       LLM: narrator        ──► prose for the resolved outcome only
             ▼
       event stream ──► frontend (REPL / voice)
```

- The LLM is a function call, not an actor.
- An `improvise` intent type catches anything the schema doesn't cover. It falls back to a generic skill roll with a defined cost.
- The game is testable without a model: replay a seed with canned intents and assert on events.

### 3.2 State

- **SQLite** holds game state. It is mutable, one database per world (seed).
- An **append-only event log** (every roll and every state diff) is used for debugging and "previously on" recaps. It is *not* used for branching.
- The engine source is the source of truth for rules. If Common Lisp is chosen, the running image is a cache: patches live in git-tracked source, never only in the image.

### 3.3 Language

Open between **Python** and **Common Lisp**:

| | Python | Common Lisp (SBCL) |
|---|---|---|
| LLM SDKs | First-party | Hand-rolled HTTP/JSON (small job) |
| Live patching | `importlib.reload`, weak | Redefine functions and classes in a running image; CLOS instance migration |
| Error recovery | Crash and restart | Conditions and restarts: fix a resolver mid-turn and retry |
| Content format | YAML / TOML | S-expressions, read with `*read-eval*` nil; macros for a rules DSL |
| LLM-assisted coding | Strong | Weaker (less training data) |
| Side benefit | — | Low-stakes testbed for the persistent-Lisp-process idea from the homelab harness |

### 3.4 Content as data ("lore packs")

The engine is setting-agnostic. A **lore pack** supplies:

- the setting bible, a lexicon, and a "never" list (tropes the narrator must avoid),
- faction, creature, item and material tables,
- set-piece and trigger definitions,
- worldgen tables and parameters,
- narrator voice and tone guidance per layer.

The exact interface is still open (§13).

---

## 4. Runs, death and seeds

- **Invocation:** `seed + run counter`. Players can choose the seed and worldgen parameters before generating a world.
- **Permadeath** applies per character. The world persists.
- **Bones:** the previous body stays where it died, with its loot. Its killer, or at least a raised local hazard, persists too. (Term borrowed from NetHack's bones files.)
- **Respawn:** the next run wakes from a vat.
- **World state persists across runs.** Structures, depleted resources, faction state, clocks, corpses, and surviving allies all remain. Allies who outlive a PC remember them.
- **Determinism caveat:** a seed reproduces the code-generated skeleton, not the LLM flavor prose. To share an identical world, share the world DB with its cached flavor text.

---

## 5. World and worldgen

A seeded, layered pipeline, run once per world and hidden from the player:

1. **Topology:** a region graph of decks, sections, corridors and vat bays, generated in code. (LLMs are poor at spatial consistency.)
2. **Ecology and hazards:** biome tables populate resources, fauna and environmental hazards.
3. **History:** the ship's past, prior wakers, ruins, faction origins. A Caves of Qud-style generated event chain is a candidate, optionally retold as unreliable in-world myth.
4. **Factions:** placement, disposition, needs, schedules.
5. **Set-piece placement,** consistent with history.
6. **LLM flavor pass:** descriptions written into the DB. This is batchable and latency-insensitive, so it's a candidate for local inference.
7. **Worldgen parameters exposed to the player:** TBD (size, history depth, hostility, faction count…).

**Map representation:** a graph. Nodes carry a `layer_id` from day one, even though only the decks layer exists in the first build.

---

## 6. Time model

- **Roguelike pacing:** time advances only when the player acts.
- **Free actions:** `look`, `examine`, `inventory`, `map`, `status`, `where`, log review. These may only describe **what is already in the DB at the PC's knowledge level.**
- **Timed actions:** move, `search` / `investigate`, craft, build, fight, eat, rest. Only timed actions can *create* new knowledge. This split stops the narrator from inventing discoveries in response to repeated free looks.
- **Ticks:** a base unit (for example ~10 minutes). Day phases (morning / afternoon / night) are derived from the tick counter.
- **Variable action costs:** searching might take an hour; building a palisade takes days.
- **Long actions are interruptible,** in the style of DCSS travel and Cataclysm: DDA activities. Hazard checks, threshold alerts, returning allies and arrivals all stop the action and return control to the player.
- **A single scheduler** (priority queue) holds PC turns, ally jobs, faction moves, clocks and weather. Events pop in time order until it's the PC's turn.

---

## 7. Probability, clocks and set pieces

### 7.1 Explicit odds

- The **engine** computes every probability as a base rate plus modifiers (skill, tools, conditions, fatigue, injury, allies assisting).
- The player sees the odds and, optionally, the breakdown: "base 20%, +15% dry tinder, +10% skill, −5% wind."
- In voice, odds are spoken plainly ("about one in three").

### 7.2 Hazard clocks

- **Rising hazard rate:** for example, a predator visit at 1% on day 1, rising to 5% by day 20.
- Know the cumulative math. That curve gives **about a 45% chance of no visit at all by day 20.**
- Convert daily rates to per-tick rates: `p_tick = 1 − (1 − p_day)^(1/ticks_per_day)`.
- Variance tools, chosen per threat:
  - **PRD** (pseudo-random distribution, as in Warcraft 3 and Dota),
  - **a hard ceiling** (guaranteed by day N),
  - **reset after the event fires.**
- **Exposure modifies the rate:** location, carried meat, light, noise. The base's defenses lower it.
- **Telegraphing:** clocks escalate through visible stages (tracks → kill site → sounds at night) before the lethal stage becomes possible. This matters doubly with permadeath.

### 7.3 Set pieces and pacing

- **Triggers:** deterministic, condition-based, fire once or on a cooldown. Example: cross a threshold region and a predator encounter fires.
- **Encounter tables** per region.
- **Storyteller layer** (RimWorld-style): gates events by pacing, for example no hostile event within N days of the last one unless the player is thriving.

---

## 8. Characters

### 8.1 The PC

- Single PC, embodied. No focus-switching.
- Stats: hydration, calories, fatigue, injuries, morale.
- Skills improve with use.

### 8.2 Allies

- **Modeled in code, voiced by the LLM.** They share the needs-and-utility model with factions.
- **Two states:** *with the PC* (they act in the scene and assist rolls) or *on a job* (one coarse roll per tick or phase against their assigned task).
- **Knowledge:** allies return with **reports**, which the engine converts into knowledge rows for the PC.
- **Anti-yes-man rule:** the engine decides refusals, arguments and desertion from loyalty, fear and the ally's own goals. Each ally has one or two hard-coded goals that can conflict with the PC's. The narrator only voices decisions already made.
- **Relationship memory:** a numeric score plus a short per-NPC list of shared events.
- **Off-screen deaths are telegraphed** through escalating reports.
- **Sources:** other vats; possibly defectors from factions.

### 8.3 Factions

- **Code-side faction model** for now: needs, disposition, schedules, utility AI.
- **The LLM is used only for voicing.**
- **Candidate mechanic:** a language or comprehension barrier, where the PC's comprehension level degrades how much dialogue the narrator renders.

---

## 9. The base (fortress mode, embodied, hybrid)

- **Embodied:** the PC builds personally. Allies take jobs. There are no god-view designations.
- **Hybrid layout:** a few **named rooms** as walkable graph nodes (for example vat bay, workshop, store, wall or gate), each with **abstract upgrade levels** rather than tile layouts.
- **Construction** is a long, interruptible timed action. Partial progress persistence is TBD.
- **The base answers the clocks:** defenses, light, walls and stores modify the hazard rates and exposure. Building toward a known, telegraphed threat is the core loop (precedents: the 7 Days to Die blood moon; Project Zomboid's helicopter event and utility shutoff).
- **Adventure mode** (later) shares the world. Practically, the boundary may just be distance from base.

---

## 10. Interface

### 10.1 Event stream

The engine emits structured events (`narration`, `status`, `alert`, `prompt`, `sound_cue`, `odds`, `roll`). Frontends render them:

- **REPL** (first build): the input line accepts engine commands and free text.
- **Voice** (later): STT in, streaming TTS out, sentence by sentence.
- **TUI** (maybe, much later).

### 10.2 Non-visual design rules

- **Pull status, push alerts.** Status is on demand. Alerts are engine-triggered when thresholds are crossed.
- **Consistent exit phrasing,** in a fixed order: "Paths: north to …, east to …".
- **Landmarks over coordinates.** `where` gives a short route home.
- **Length caps** on narration, set per frontend. Voice turns are about 2–4 sentences; `look closer` for more.
- **The narrator register shifts per layer.** On foot it's close and sensory; on the bridge (later) it's terse and procedural.

### 10.3 Voice specifics (deferred)

- Turn-based narration tolerates 1–3 s of latency far better than a home-assistant voice agent does.
- Confirm **irreversible or lethal-risk** actions, because speech-recognition errors meet permadeath.
- Use a small fixed vocabulary for engine commands.
- Support barge-in ("stop", "skip").
- **Sonification (optional):** clock hazard rates mapped to ambient sound that thickens as danger rises. SuperCollider is a candidate.

---

## 11. Layers and zoom (designed for, not built)

- Every layer is a graph with its own **tick scale, verb set and narrator prompt.**
  - Decks: minutes.
  - Ship command: hours or days.
  - Interplanetary transit: weeks.
- **Layers below the active one run at LOD** (level-of-detail simulation): coarse rolls, then a "while you were on the bridge" report when you return.
- **Transitions are places:** the captain's seat, a lander bay, an airlock. Zooming is movement, not a menu.
- **First-build seam only:** a `layer_id` on nodes, per-layer tick scale in the scheduler, and transition node types. Finding the captain's seat could end the first build as a locked door.
- Precedent: *Starflight* (1986), *Sunless Sea*.

---

## 12. LLM roles and guardrails

| Role | Input | Output | Constraint |
|---|---|---|---|
| Intent parser | Player text + known context | Schema-validated JSON intent | Never resolves anything |
| Narrator | Resolved outcome + state snapshot + PC knowledge | Prose within a length cap | Never decides PC actions, thoughts or emotions; never adds outcomes |
| Voice actor | NPC state (traits, mood, loyalty, decision) | Dialogue | Voices decisions already made by the engine |
| Worldgen flavor | Generated skeleton rows | Descriptions written to the DB | Batch, offline, cached |

- **Facts ledger:** details the narrator invents are recorded so they can't be contradicted later. Whether they're accepted automatically or checked first is open.
- **Model split (untested):** local model for the worldgen flavor pass; cloud model for the turn loop, where tool and schema discipline matters most. Test by running the same 20-turn script on both.

---

## 13. Data model sketch

```
worlds(seed, params, created_at, engine_version)
runs(id, seed, n, started_tick, ended_tick, cause_of_death, death_node)
nodes(id, layer_id, name, kind, biome, flavor)
edges(from_id, to_id, cost_ticks, hazard_mod)
resources(node_id, kind, qty, regen_rate, skill_req)
items(id, kind, owner_id | node_id, durability)
characters(id, kind[pc|ally|faction_npc], faction_id, node_id, stats_json, needs_json, order_json, alive)
relationships(a_id, b_id, score)
npc_facts(npc_id, text, tick)
knowledge(actor_id, subject, detail, tick)        -- PC fog of war
facts(id, subject, text, source[narrator|worldgen], tick)
factions(id, disposition, needs_json, schedule_json)
clocks(id, kind, curve_json, stage, p_current, last_fired)
triggers(id, condition, effect, fired, cooldown)
base_rooms(id, node_id, kind, upgrade_level, progress)
corpses(run_id, node_id, items_json, decay)
schedule(tick, priority, event_json)
log(tick, kind, payload_json)                     -- append-only
```

---

## 14. First build (vertical slice)

**In scope:**

- worldgen for a single decks layer,
- vat spawn,
- REPL with engine commands and free text,
- free vs timed actions,
- the scheduler with interrupts,
- explicit odds,
- one or two telegraphed hazard clocks,
- one or two set pieces,
- hybrid base with 3–4 rooms,
- one ally source,
- one code-side faction,
- permadeath with bones and respawn,
- a locked captain's-seat door as the end of the slice.

**Out of scope:** voice, sonification, TUI, additional layers, adventure mode, LLM-driven factions, AI-authored rules.

**Success test:** is a death-and-respawn loop on one seed fun as text alone?

---

## 15. Parked ideas

- **AI patches the engine.** Set aside: it conflicts with pillar 1, breaks reproducibility, and Common Lisp has no built-in sandbox. A softer form remains possible: the AI proposes rules into a review queue between sessions, the designer approves them, and they enter content packs as interpreted data, never `eval`'d. The only seam needed now is the `improvise` intent.
- **PC focus-switching.** Dropped as too daunting. Allies cover most of the value.
- **Factions as separate LLM agents.**
- **TUI frontend.**
- **Planetary landers and surface worldgen.**

---

## 16. Open questions

**Core identity**
1. Engine language: Python or Common Lisp.
2. Engine scope: a general roguelike engine with lore packs, or one game with a clean engine? ("Build the game" argues for the latter; lore packs argue for some generality.)
3. Lore-pack interface: what exactly a pack must provide, and in what format.
4. Canon direction: can anything generated in play ever feed back into the book's canon, or is the game explicitly non-canonical?

**Fiction and runs**

5. Do clones remember across runs? (In-fiction meta-knowledge, as in *Outer Wilds* / *Returnal* / *Hades*, vs. amnesia.)
6. Is the ship a revelation (Wolfe-style: inhabitants don't know) or a known premise?
7. Does the world tick forward between a death and the next vat waking? How much?
8. Which worldgen parameters are exposed to the player?
9. Do shared seeds need identical prose (share the DB), or is identical structure enough?

**Time and odds**

10. Tick length, and whether players see ticks or only phases.
11. Is partial progress on an interrupted long action saved?
12. Does `search` have diminishing returns in one spot?
13. Per threat: rising hazard, PRD, or hard ceiling? Which tick does each clock roll on?
14. Are clocks and their stages visible, hidden, or only conveyed through telegraphing?

**Narration**

15. Are narrator-invented facts auto-canon, or engine-checked first?
16. Model split: does local inference hold up for anything beyond the worldgen flavor pass?

**Characters**

17. Allies: standing orders, autonomous needs, or both?
18. Ally sources beyond other vats.
19. Factions: is the language barrier a mechanic? What is the first faction's disposition and agenda?

**Base**

20. Which 3–4 rooms make up the first base, and how does each upgrade modify which hazards?
21. Where is the fortress/adventure boundary: a mode switch, or distance from base?

**Interface**

22. Voice: when does it become first-class?
23. Sonification: none, alerts only, or ambient clocks?
24. Confirmation threshold: all risky actions, or only lethal ones?

**Deferred layers**

25. Orbital navigation: abstract graph or simulated?

---

## 17. Prior art

- **Embodied survival / base-building roguelikes:** Cataclysm: Dark Days Ahead (especially faction camps), UnReal World, Kenshi, Project Zomboid, 7 Days to Die.
- **Text and non-visual:** A Dark Room, Survive the Wild (audiogames.net), MUDs with player housing, Infocom-style interactive fiction.
- **Systems:** NetHack (bones files), DCSS / Angband (energy and speed, interrupts), RimWorld (storyteller), Caves of Qud (generated, mythologized history), Dwarf Fortress (worldgen; fortress and adventure in one world), Warcraft 3 / Dota (PRD), PbtA (GM moves), Ironsworn / Mythic GME (solo oracles).
- **Multi-scale:** Starflight, Sunless Sea.
- **Fiction:** Gene Wolfe, *Book of the Long Sun* (and *Short Sun* for landers); *Robinson Crusoe*; Firefly.
