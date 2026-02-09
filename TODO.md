# MedSync AI v2 — Outstanding Issues

## Session State Race Condition (HIGH)

**Risk**: If the same user sends two rapid messages, both requests share the same `session_state` dict (loaded from Firestore by user ID). Concurrent reads/writes to `conversation_history` could produce corrupted state — e.g., messages out of order or dropped entries.

**Where**: `main.py` loads session state per request using `uid`. Two concurrent requests for the same `uid` each get a copy from Firestore, append their own messages, and write back. The last writer wins, potentially dropping the other request's conversation turn.

**Impact**: Only affects same-user rapid-fire messages (e.g., double-click send). Different users are fully isolated.

**Possible fixes**:
- Per-user async lock (`asyncio.Lock` keyed by `uid`) — simple, prevents concurrent pipeline runs for same user
- Optimistic concurrency on Firestore writes (version field + retry)
- Queue per user — serialize requests for same uid

**Priority**: HIGH but low probability in practice (requires same user sending overlapping requests). Fix when adding production hardening.
