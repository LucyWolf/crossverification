"""The example issuer, started for real and asked over HTTP.

The unit tests cover the decisions; this one covers the wiring. It starts
`examples/fastapi_issuer.py` on a local port and sends the same requests a partner would —
so a mistake in how the callbacks hang together shows up here rather than in production.

    pip install fastapi uvicorn
    python3 tests/test_endtoend.py

Skipped with a clear message when fastapi or uvicorn is missing; it is the one test with
dependencies.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

try:
    import uvicorn
    from examples.fastapi_issuer import app
except ImportError as err:
    print(f"skipped: {err.name or err} is not installed (pip install fastapi uvicorn)")
    sys.exit(0)

PORT = 8777
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(60):
    time.sleep(0.1)
    if server.started:
        break
else:                                                       # pragma: no cover
    print("the example server did not come up")
    sys.exit(1)


def post(path, **fields):
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=body)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


KEY = "demo-key-please-replace"
cases = [
    ("a vetted member", post("/coop/check", key=KEY, user_id="900"),
     (200, {"verified": True})),
    ("a member without the role", post("/coop/check", key=KEY, user_id="901"),
     (200, {"verified": False})),
    ("somebody unknown", post("/coop/check", key=KEY, user_id="404"),
     (200, {"verified": False})),
    # The important one: over the wire, a wrong key must look exactly like a plain no.
    ("a wrong key", post("/coop/check", key="x" * 30, user_id="900"),
     (403, {"verified": False})),
    ("a missing user id", post("/coop/check", key=KEY), (400, {"verified": False})),
    ("info", post("/coop/info", key=KEY),
     (200, {"ok": True, "server": "Example Community", "roles": ["Verified 18+"]})),
    ("info with a wrong key", post("/coop/info", key="y" * 30), (403, {"ok": False})),
]

failed = 0
for name, got, want in cases:
    ok = got == want
    failed += 0 if ok else 1
    print(("  ok  " if ok else "  XX  ") + name + ("" if ok else f"  -> {got} not {want}"))

print(f"\n{len(cases) - failed}/{len(cases)} against a running server")
sys.exit(1 if failed else 0)
