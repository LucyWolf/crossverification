"""The issuer side in a FastAPI bot — the whole wiring, nothing left out.

Run it:
    pip install fastapi uvicorn
    python3 examples/fastapi_issuer.py

Then, from somewhere else:
    curl -X POST localhost:8000/coop/check -d "key=demo-key-please-replace" -d "user_id=900"

Replace the two lookups marked TODO with your own. Everything else stays as it is.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Form                       # noqa: E402
from fastapi.responses import JSONResponse              # noqa: E402

from crossverification import (                         # noqa: E402
    Partner, RateLimiter, answer_check, answer_info, key_hash, shared_with,
)

app = FastAPI()

# One limiter for the whole process, shared by both endpoints. Counting per key is the
# point - see SPEC.md §5.
limiter = RateLimiter()

# ── TODO: your storage ────────────────────────────────────────────────────────
# Store the HASH, never the key itself. What you keep next to it is yours; this example
# keeps the bare minimum the protocol needs.
PAIRINGS = {
    key_hash("demo-key-please-replace"): Partner(
        name="Example partner",
        server_name="Example Community",
        shared_roles=frozenset({"111222333444555666"}),
        shared_role_names=("Verified 18+",),
        enabled=True,
    ),
}

# ── TODO: your member lookup ──────────────────────────────────────────────────
# In a discord.py bot this is guild.get_member(int(user_id)) and its .roles.
MEMBER_ROLES = {"900": {"111222333444555666"}, "901": {"999"}}


def find_partner(key: str):
    return PAIRINGS.get(key_hash(key))


def holds_role(user_id: str, partner: Partner) -> bool:
    # Current roles, not past ones: a verification that was taken away is not a
    # verification, and this is the line where that is decided.
    return shared_with(MEMBER_ROLES.get(user_id, set()), partner)


@app.post("/coop/check")
async def coop_check(key: str = Form(""), user_id: str = Form("")):
    answer = await answer_check(key, user_id, find_partner, holds_role, limiter)
    return JSONResponse(answer.body, status_code=answer.status)


@app.post("/coop/info")
async def coop_info(key: str = Form("")):
    answer = await answer_info(key, find_partner, limiter)
    return JSONResponse(answer.body, status_code=answer.status)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
