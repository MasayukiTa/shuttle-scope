# Conversational Scope System (rule-based)

Date: 2026-05-23
Status: Adopted (Slice Z+1)

## Motivation

The Growth Advisor chat already extracts a single-turn period via `parsePeriod()`.
Users want filters they mention in turn N (`先月の` / `smash の` / `バック奥の`)
to **persist** across turns until they explicitly change them — so they can ask
follow-up questions like "じゃあバック奥では?" without re-stating the period and
shot context.

We deliberately implement this **without an LLM**:

- **Latency**: regex/synonym lookup is O(text length), <1 ms; no API round-trip.
- **Determinism**: the same input always produces the same scope. Auditable.
- **Cost**: zero per-call cost vs. NIM/OpenAI tokens.
- **Safety**: the chat lives behind the existing harness; an LLM here would
  expand the attack surface (prompt injection, prompt leak).

LLMs may be layered in later as a fallback for *uncovered* phrasing, but the
deterministic layer is the source of truth.

## Slot system

A **slot** is a typed scope dimension. Each slot has:

- a server extractor (rule-based) in `backend/analysis/chat/slot_extractors.py`
- a client extractor mirror in `src/utils/parseSlots.ts`
- a normalized JSON shape stored on `chat_sessions.current_scope`

Current slots:

| Slot       | Shape                                             | Examples (ja / en)                                          |
| ---------- | ------------------------------------------------- | ----------------------------------------------------------- |
| `period`   | `{date_from, date_to, label}`                     | `先月`, `直近3ヶ月`, `2026/03/01〜2026/03/31`, `past 7 days`  |
| `shot_type`| `{code, label}` — `smash|clear|drop|net|drive|push|lob|serve` | `スマッシュ`, `ヘアピン`, `smash`, `net shot`            |
| `zone`     | `{code, label}` — `FL|FR|BL|BR|FRONT|BACK|SIDE`   | `バック奥`, `フォア前`, `コート奥`                          |

Extending: add a new entry to `_SHOT_SYNONYMS` / `_ZONE_SYNONYMS` (or a new
extractor for a brand-new slot), mirror it to TS, and add the slot key to
`scope_merger._SLOTS` + the router schema. Each slot is independent.

## Merge semantics

- **Last-write-wins per slot.** If turn N extracts `{shot_type: smash}` and
  turn N+1 extracts `{shot_type: clear}`, the new value replaces the old.
- **Slots not touched in this turn are preserved.** Mentioning only "バック奥"
  in turn N+1 does not drop `period` from turn N.
- **Client-side confirmed values beat server-side extracted values.** The chat
  composer already shows a confirmation chip for `period`; if the user edits or
  manually applies a range, that value is sent in the body (`date_from`/`date_to`)
  and overrides whatever the extractor would have picked.
- **Explicit clear language** (`リセット`, `全部リセット`, `全部クリア`, `reset all`,
  `clear all`) wipes the whole scope. Per-slot clear phrases (`全期間`, `全エリア`)
  drop that slot only.
- **Frontend chip `[✕]`** sends `{clear_slots: ["period"]}` next message — server
  treats it identically to a clear-signal in text.

## Persistence

`chat_sessions.current_scope` is a JSON column added in migration `0037`:

```jsonc
{
  "period":    { "date_from": "2026-04-01", "date_to": "2026-04-30", "label": "先月" },
  "shot_type": { "code": "smash", "label": "スマッシュ" },
  "zone":      { "code": "BR", "label": "バック奥" },
  "updated_turn": 5,
  "history": [
    { "turn": 1, "slot": "period",    "value": {...}, "source": "extracted" },
    { "turn": 1, "slot": "shot_type", "value": {...}, "source": "extracted" },
    { "turn": 2, "slot": "zone",      "value": {...}, "source": "extracted" },
    { "turn": 3, "slot": "__all__",   "value": null,  "source": "extracted" }
  ]
}
```

`history` is bounded to the last 100 entries to keep the column small.

The endpoint `POST /api/insights/chat/sessions/{sid}/messages` returns
`applied_scope` (the post-merge view) so the frontend can render
`ActiveScopeBar` immediately. `GET /sessions/{sid}/messages` also returns
`applied_scope` for resumed sessions.

## Flow

```
 user text "バック奥のスマッシュは?"
        │
        ▼
 ┌──────────────────────────┐
 │ client: parseAllSlots()  │  ←─ chip preview in composer (instant)
 └──────────────────────────┘
        │ POST { content, date_from?, date_to?, shot_type?, zone?, clear_slots[] }
        ▼
 ┌──────────────────────────┐
 │ server: extract_all()    │  ─→ deltas { period, shot_type, zone }
 │ + client body            │  ─→ deltas overridden by client values
 │ + clear_signals(text)    │  ─→ slot deletions
 │ + body.clear_slots       │
 └──────────────────────────┘
        │
        ▼
 ┌──────────────────────────┐
 │ merge_scope(prev, deltas)│  ←─ last-write-wins per slot
 └──────────────────────────┘
        │
        ▼
 sess.current_scope ← new_scope   (persisted JSON)
        │
        ▼
 build_player_summary(scope.period)  ──→  AI response
        │
        ▼
 response: { ai_message, applied_scope }
        │
        ▼
 ActiveScopeBar re-renders with active chips
```

## Future slots to consider

- `opponent` — opponent player_id / display name ("vs Player D")
- `set_range` — set index range ("1〜2セット目だけ")
- `score_state` — leading / trailing / tied
- `match_phase` — early / mid / late
- `condition_tag` — RPE, Hooper threshold bands

Each can be added without changing merge semantics — just register a new
extractor + slot key.

## Why rule-based, not LLM

| Concern    | Rule-based                          | LLM                                 |
| ---------- | ----------------------------------- | ----------------------------------- |
| Latency    | <1 ms                               | 200–1500 ms                         |
| Cost       | $0                                  | Per-token                           |
| Determinism| Identical every time                | Sampling jitter                     |
| Audit      | Read the synonym table              | Black box                           |
| Safety     | Cannot leak prompts or be jailbroken| Prompt-injection surface            |
| Recall     | Bounded by synonym list             | Higher on novel phrasing            |

The synonym list is small enough to maintain manually, and falling back to
"unknown" is a *good* failure mode here — the chat still answers, just without
the inferred filter.

## Testing

- `backend/tests/test_slot_extractors.py` — 18 cases incl. negation parity
- `backend/tests/test_chat_scope.py` — end-to-end multi-turn persistence,
  individual clear, full reset, client-period override, GET resume
- `src/utils/__tests__/parseSlots.test.ts` — 11 vitest cases mirroring the
  backend extractors
