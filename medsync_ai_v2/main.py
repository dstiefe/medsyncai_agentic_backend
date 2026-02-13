"""
MedSync AI v2 - FastAPI Entry Point

SSE-streaming API endpoint for the medical device compatibility system.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import json
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from medsync_ai_v2.shared.session_state import SessionManager
from medsync_ai_v2.shared.device_search import get_database, get_text_search, build_whoosh_index, FirebaseDB
from medsync_ai_v2.orchestrator.orchestrator import Orchestrator
from medsync_ai_v2 import config


# ── App Setup ─────────────────────────────────────────────────

app = FastAPI(title="MedSync AI v2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("MedSync AI v2 API starting...")

session_manager = SessionManager()
orchestrator = Orchestrator()


async def _update_user_tokens(uid: str, input_tokens: int, output_tokens: int):
    """Fire-and-forget: atomically increment user-level token counters."""
    try:
        firebase = FirebaseDB(
            cred_path=config.FIREBASE_CRED_PATH,
            collection_name=config.FIREBASE_USERS_COLLECTION,
        )
        await firebase.update_user_tokens_async(
            doc_id=uid,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
        print(f"  [Tokens] Updated user {uid}: +{input_tokens} in, +{output_tokens} out")
    except Exception as e:
        print(f"  [Tokens] Failed to update user {uid}: {e}")


@app.on_event("startup")
async def startup_load_database():
    """Preload Firebase database and Whoosh index at startup."""
    print("Loading device database from Firebase...")
    await asyncio.to_thread(get_database)
    print("Loading text search data...")
    await asyncio.to_thread(get_text_search)
    print("Building Whoosh search index...")
    await asyncio.to_thread(build_whoosh_index)
    print("Startup complete — database and search index ready.")


# ── Streaming Broker ──────────────────────────────────────────

class StreamingBroker:
    """Async queue-based SSE broker."""

    def __init__(self):
        self._q = asyncio.Queue()
        self._closed = asyncio.Event()

    async def put(self, item: dict):
        await self._q.put(item)

    async def close(self):
        if not self._closed.is_set():
            await self._q.put({"type": "__BROKER_EOF__"})
            self._closed.set()

    async def iterate(self):
        while True:
            item = await self._q.get()
            self._q.task_done()
            if item.get("type") == "__BROKER_EOF__":
                break
            yield item


# ── Background Orchestrator Runner ────────────────────────────

async def run_orchestrator_with_broker(
    uid: str,
    session_id: str,
    session_state: dict,
    broker: StreamingBroker,
):
    """Run the orchestrator and stream results via broker."""
    try:
        conversation_history = session_state.get("conversation_history", [])

        # Run orchestrator (broker receives per-agent status events)
        final_text, tool_log, token_usage, chain_data = await orchestrator.run(
            conversation_history=conversation_history,
            session_state=session_state,
            broker=broker,
        )

        # Append assistant response to conversation history
        session_state["conversation_history"].append({
            "role": "assistant",
            "content": final_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Output agents stream final_chunk events directly via broker
        # (no post-hoc chunking needed)

        # Stream chain_category_chunk if we have device data
        print(f"  [SSE] chain_data type={type(chain_data).__name__}, "
              f"len={len(chain_data) if hasattr(chain_data, '__len__') else 'N/A'}, "
              f"truthy={bool(chain_data) if chain_data is not None else False}")
        if chain_data:
            chunk_size_devices = 20
            total_devices = len(chain_data)
            for i in range(0, total_devices, chunk_size_devices):
                chunk = chain_data[i : i + chunk_size_devices]
                await broker.put({
                    "type": "chain_category_chunk",
                    "data": {
                        "agent": "chain_output_agent",
                        "devices": chunk,
                        "chunk_info": {
                            "chunk_number": i // chunk_size_devices + 1,
                            "chunk_size": len(chunk),
                            "total_devices": total_devices,
                            "is_final_chunk": (i + chunk_size_devices) >= total_devices,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

        # Save token usage to session state (before persist so it's included)
        session_state.setdefault("tokens", {})
        session_state["tokens"]["orchestrator"] = token_usage
        session_state["tokens"]["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Save session
        await session_manager.save_chat_state(uid, session_id, session_state)

        # Increment user-level token counters (non-blocking)
        total_in = token_usage.get("total_input_tokens", 0)
        total_out = token_usage.get("total_output_tokens", 0)
        if total_in > 0 or total_out > 0:
            asyncio.create_task(_update_user_tokens(uid, total_in, total_out))

        # Notify: turn complete
        await broker.put({
            "type": "turn_complete",
            "data": {
                "uid": uid,
                "session_id": session_id,
                "turn_index": len([
                    m for m in session_state.get("conversation_history", [])
                    if m.get("role") == "assistant"
                ]),
                "token_usage": {
                    "input_tokens": token_usage.get("total_input_tokens", 0),
                    "output_tokens": token_usage.get("total_output_tokens", 0),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        })

        await broker.close()

    except Exception as e:
        import traceback
        traceback.print_exc()
        await broker.put({
            "type": "error",
            "data": {
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
        })
        await broker.close()


# ── Endpoints ─────────────────────────────────────────────────

@app.post("/chat/stream")
async def chat_stream(request: Request):
    """Main chat endpoint with SSE streaming."""
    data = await request.json()

    uid = data["uid"]
    message = data["message"]

    print(f"Incoming message from {uid}: {message[:100]}")

    # Load or create session
    session_id = data.get("session_id") or session_manager.create_session(uid)
    session_state = await session_manager.get_session(uid, session_id)

    # Ensure base structure
    session_state.setdefault("conversation_history", [])
    session_state.setdefault("uid", uid)
    session_state.setdefault("session_id", session_id)

    # Append user message
    session_state["last_user_input"] = message
    session_state["conversation_history"].append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Save in background (don't block orchestrator startup)
    asyncio.create_task(session_manager.save_chat_state(uid, session_id, session_state))

    # Set up SSE streaming
    broker = StreamingBroker()

    async def sse():
        try:
            async for event in broker.iterate():
                event.setdefault("data", {})
                event["data"]["uid"] = uid
                event["data"]["session_id"] = session_id
                yield "data: " + json.dumps(event, default=str) + "\n\n"
        finally:
            await broker.close()

    # Run orchestrator in background
    asyncio.create_task(
        run_orchestrator_with_broker(
            uid=uid,
            session_id=session_id,
            session_state=session_state,
            broker=broker,
        )
    )

    return StreamingResponse(sse(), media_type="text/event-stream")

#
#
@app.get("/checker")
async def checker():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.8"}
