# API Conventions

## Authentication
All routes must use the shared `require_auth` dependency:

```python
from fastapi import APIRouter, Depends
from app.shared.auth import require_auth

router = APIRouter(prefix="/your-engine", tags=["your-engine"], dependencies=[Depends(require_auth)])
```

`require_auth` validates that every POST/PUT/PATCH request body contains `uid` and
creates a `session_id` if one is not provided. It attaches both to `request.state`.

## POST Only — No GET for Authenticated Data
All data endpoints must be POST. GET is reserved for health checks only.

```python
# WRONG
@router.get("/results")
async def get_results(uid: str = Query(...)):

# CORRECT
@router.post("/results")
async def get_results(request: ResultsRequest):
```

## Every Request Model Includes uid and session_id
```python
class YourRequest(BaseModel):
    uid: str                          # required — 401 if missing
    session_id: Optional[str] = None  # backend creates if blank
    # ... other fields
```

## Every Response Includes session_id
```python
@router.post("/results")
async def get_results(request: YourRequest, http_request: Request):
    session_id = http_request.state.session_id
    return {"session_id": session_id, ...}
```

## Health Checks Are the Only Open GET Endpoints
```python
@router.get("/health")  # No require_auth — intentionally open
async def health():
    return {"status": "ok"}
```

## Route Structure
- All routes live under `app/agents/<engine_name>/routes.py`
- Group routes by engine/resource, not by HTTP method
- Always use async/await — never `.then()` chains
- Always handle errors explicitly — never swallow exceptions silently
- Base URLs always come from environment variables — never hardcode them

## Response Shape
- Successful responses return `_build_return()` output (see CLAUDE.md)
- Error responses always include a human-readable `error` message
- Use 422 for validation errors, 401 for auth, 403 for permissions, 404 for not found

## Frontend API Contract
See `app/.notes/api-contract-frontend.md` for the full frontend contract.
