"""
MedSync AI v2 - Session State Management

Handles user conversation sessions with Firebase persistence.
Ported from vs2/llm_utils.py SessionManager.
"""

import json
import uuid
import asyncio
from datetime import datetime, timezone
from medsync_ai_v2.shared.device_search import FirebaseDB
from medsync_ai_v2 import config


class SessionManager:
    """
    Handles user sessions stored in Firebase.
    Structure:
        users/{uid}/chats/{session_id}                      -> SessionState
        users/{uid}/chats/{session_id}/turn_history/{turn}   -> TurnState
    """

    def __init__(self):
        self.sessions = {}  # Cache: (uid, session_id) -> session_state
        self.locks = {}     # Concurrency locks

    def _get_firebase(self):
        return FirebaseDB(
            cred_path=config.FIREBASE_CRED_PATH,
            collection_name=config.FIREBASE_USERS_COLLECTION,
        )

    def create_session(self, uid: str) -> str:
        session_id = str(uuid.uuid4())
        session_state = {
            "uid": uid,
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "conversation_history": [],
            "reasoning_context_snapshot": {},
            "last_turn_id": None,
            "tokens": {},
        }
        self.sessions[(uid, session_id)] = session_state
        return session_id

    def _get_lock(self, uid: str, session_id: str) -> asyncio.Lock:
        """Get or create a per-session lock for safe concurrent access."""
        key = (uid, session_id)
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        return self.locks[key]

    async def get_session(self, uid: str, session_id: str) -> dict:
        key = (uid, session_id)
        lock = self._get_lock(uid, session_id)

        async with lock:
            # In-memory cache
            if key in self.sessions:
                return self.sessions[key]

            # Firestore lookup
            firebase = self._get_firebase()
            session_doc = await firebase.get_subcollection_doc_async(
                parent_id=uid,
                subcollection_name="chats",
                doc_id=session_id,
            )

            if session_doc:
                self.sessions[key] = session_doc
                return session_doc

            # Create new if missing
            new_id = self.create_session(uid)
            return self.sessions[(uid, new_id)]

    async def save_session(self, uid: str, session_id: str, session_state: dict):
        key = (uid, session_id)
        lock = self._get_lock(uid, session_id)

        async with lock:
            self.sessions[key] = session_state
            firebase = self._get_firebase()
            await firebase.save_to_subcollection_async(
                parent_id=uid,
                subcollection_name="chats",
                doc_id=session_id,
                data=session_state,
            )

    async def save_chat_state(self, uid: str, session_id: str, data: dict):
        lock = self._get_lock(uid, session_id)

        async with lock:
            firebase = self._get_firebase()
            await firebase.add_subcollection_document_async(
                parent_doc_id=uid,
                subcollection_name="chats",
                data=data,
                doc_id=session_id,
            )

    async def save_turn(self, uid: str, session_id: str, turn_id: str, turn_record: dict):
        firebase = self._get_firebase()
        await firebase.save_to_nested_subcollection_async(
            parent_id=uid,
            subcollection_path=f"chats/{session_id}/turn_history",
            doc_id=turn_id,
            data=turn_record,
        )

    async def get_turn(self, uid: str, session_id: str, turn_id: str):
        firebase = self._get_firebase()
        # Walk nested path manually
        doc_ref = firebase.db.collection(config.FIREBASE_USERS_COLLECTION).document(uid).collection("chats").document(session_id).collection("turn_history").document(turn_id)
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None

    async def update_session(self, uid: str, session_id: str, session_state: dict):
        firebase = self._get_firebase()
        clean_state = sanitize_for_firestore(session_state)
        await firebase.save_to_subcollection_async(
            parent_id=uid,
            subcollection_name="chats",
            doc_id=session_id,
            data=clean_state,
        )
        self.sessions[(uid, session_id)] = session_state

    async def end_session(self, uid: str, session_id: str):
        self.sessions.pop((uid, session_id), None)
        self.locks.pop((uid, session_id), None)


def sanitize_for_firestore(value):
    """Recursively ensure all dict keys are valid Firestore field paths."""
    if isinstance(value, dict):
        new_dict = {}
        for k, v in value.items():
            if k is None or k == "":
                k = "_empty"
            elif isinstance(k, (int, float)):
                k = str(k)
            elif not isinstance(k, str):
                k = str(k)
            k = k.replace(".", "_")
            new_dict[k] = sanitize_for_firestore(v)
        return new_dict
    elif isinstance(value, list):
        return [sanitize_for_firestore(item) for item in value]
    else:
        return value
