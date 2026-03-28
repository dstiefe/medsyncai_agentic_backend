"""
Shared authentication dependency.

Validates uid and ensures session_id exists for every POST/PUT/PATCH request.
Mirrors the pattern in /chat/stream:
    uid = data["uid"]
    session_id = data.get("session_id") or session_manager.create_session(uid)

Attaches both to request.state so every endpoint can use them without
repeating the create-if-missing logic.
"""

import json
import uuid
from fastapi import Request, HTTPException


async def require_auth(request: Request) -> None:
    """
    Validate uid and ensure session_id for all mutating requests.

    GET requests are skipped — health checks are intentionally open.

    Sets on request.state:
        uid        — validated Firebase user id
        session_id — provided by client or newly created UUID
    """
    if request.method not in ("POST", "PUT", "PATCH"):
        return

    body = await request.body()
    if not body:
        raise HTTPException(status_code=401, detail="uid is required")

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    uid = data.get("uid")
    if not uid or not str(uid).strip():
        raise HTTPException(status_code=401, detail="uid is required")

    session_id = data.get("session_id") or str(uuid.uuid4())

    request.state.uid = uid
    request.state.session_id = session_id
