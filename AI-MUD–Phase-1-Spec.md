# AI MUD MVP – Phase 1 Implementation Spec

## 0. Project Goal

Build a **single-player AI-native MUD** with:
- Persistent world state
- Multi-agent orchestration
- Text-based gameplay
- 2D scene backgrounds
- NPC character cards
- Dynamic BGM mood

This MVP focuses on **world correctness and system architecture**, not visual polish.

---

## 1. High-Level Architecture

### Components

- **Frontend (Next.js)**
  - UI rendering only
  - Sends player intent
  - Renders events, text, background, NPC portraits, BGM state

- **Backend (Python / FastAPI)**
  - World authority
  - World state storage
  - Agent orchestration
  - Rule enforcement
  - Event log
  - Deterministic simulation core

Frontend must NEVER be the source of truth.

---

## 2. Core Design Principles

1. World state is **structured, persistent, and deterministic**
2. AI agents may suggest, but **only the system mutates world state**
3. Rules can refuse player actions
4. Narrative output is separated from presentation
5. Randomness is explicit and seed-based
6. Same world state + same action → same world result (text may vary)

---

## 3. Backend Core Modules

### 3.1 World State

Use structured schemas (Pydantic).

#### WorldState
```python
WorldState:
  world_id: str
  time: int
  locations: dict[str, Location]
  npcs: dict[str, NPC]
  players: dict[str, Player]
  flags: dict[str, bool]
