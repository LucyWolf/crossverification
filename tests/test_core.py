"""Tests for the reference implementation. No network, no framework, no dependencies.

    python3 tests/test_core.py

The checks are grouped the way the specification is, and the ones that matter most are the
ones about what must NOT be visible in an answer: an unknown key has to look exactly like an
unknown person, or the endpoint becomes a way to find valid keys by trying.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crossverification import (                                   # noqa: E402
    Outcome, Partner, RateLimiter, answer_check, answer_info,
    ask_partner_sync, is_public_url, key_hash, new_key, shared_with,
)
from crossverification.client import _read_check, _read_info      # noqa: E402

passed = 0
failed = []


def check(name, condition, extra=""):
    global passed
    if condition:
        passed += 1
    else:
        failed.append(f"{name} {extra}".strip())


# ── Keys ──────────────────────────────────────────────────────────────────────
a, b = new_key(), new_key()
check("two keys differ", a != b)
check("a key is long enough to be unguessable", len(a) >= 40, f"-> {len(a)}")
check("hashing is stable", key_hash(a) == key_hash(a))
check("different keys hash differently", key_hash(a) != key_hash(b))
check("the hash does not contain the key", a not in key_hash(a))
check("an empty key still hashes", len(key_hash("")) == 64)


# ── The issuer side ───────────────────────────────────────────────────────────
PARTNER = Partner(
    name="Partner",
    shared_roles=frozenset({"111", "222"}),
    shared_role_names=("Verified 18+", "Trusted"),
    server_name="Example Community",
)
KEY = "a-real-key-that-is-long-enough-to-pass"
MEMBERS = {"900": {"111"}, "901": {"333"}}      # 900 holds a shared role, 901 does not


def find(key):
    return PARTNER if key == KEY else None


def holds(user_id, partner):
    return shared_with(MEMBERS.get(user_id, set()), partner)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


r = run(answer_check(KEY, "900", find, holds))
check("a vetted member is a yes", r.status == 200 and r.body == {"verified": True}, f"-> {r}")

r = run(answer_check(KEY, "901", find, holds))
check("a member without the role is a no", r.status == 200 and r.body == {"verified": False})

r = run(answer_check(KEY, "999", find, holds))
check("somebody unknown is a no", r.status == 200 and r.body == {"verified": False})

# The one that matters: a wrong key must not be distinguishable from an unknown person by
# the BODY. The status differs on purpose - that is what tells a partner their pairing is
# broken - but nothing in the payload may give a key-guesser a signal.
wrong = run(answer_check("wrong-key", "900", find, holds))
check("a wrong key is rejected", wrong.status == 403, f"-> {wrong.status}")
check("and looks exactly like a no", wrong.body == {"verified": False}, f"-> {wrong.body}")

off = run(answer_check(KEY, "900",
                       lambda k: Partner(shared_roles=frozenset({"111"}), enabled=False),
                       holds))
check("a disabled pairing is rejected", off.status == 403)

empty = run(answer_check(KEY, "900",
                         lambda k: Partner(shared_roles=frozenset()), holds))
check("a pairing sharing nothing answers no", empty.status == 200
      and empty.body == {"verified": False})

for bad in ("", "   ", "abc", "12a", "-5", "9" * 40):
    r = run(answer_check(KEY, bad, find, holds))
    check(f"malformed user id refused ({bad!r})", r.status == 400, f"-> {r.status}")

r = run(answer_check("", "900", find, holds))
check("a missing key is refused", r.status == 400)

# Role ids as ints on one side and strings on the other is the classic silent-no bug.
check("ids compare across int and str",
      shared_with([111, 999], Partner(shared_roles=frozenset({"111"}))))
check("and a genuine mismatch is still a no",
      not shared_with([999], Partner(shared_roles=frozenset({"111"}))))


# ── Async callbacks have to work too ──────────────────────────────────────────
async def find_async(key):
    return PARTNER if key == KEY else None


async def holds_async(user_id, partner):
    return shared_with(MEMBERS.get(user_id, set()), partner)


r = run(answer_check(KEY, "900", find_async, holds_async))
check("async callbacks work", r.body == {"verified": True}, f"-> {r.body}")


# ── The info endpoint ─────────────────────────────────────────────────────────
r = run(answer_info(KEY, find))
check("info answers", r.status == 200 and r.body["ok"] is True)
check("info names the server", r.body["server"] == "Example Community")
check("info lists the shared role names",
      r.body["roles"] == ["Verified 18+", "Trusted"], f'-> {r.body["roles"]}')
check("info leaks no role ids",
      "111" not in json.dumps(r.body) and "222" not in json.dumps(r.body),
      f"-> {r.body}")
check("info rejects a wrong key", run(answer_info("nope", find)).status == 403)
check("info refuses an empty key", run(answer_info("", find)).status == 400)


# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = RateLimiter(per_minute=3)
codes = [run(answer_check(KEY, "900", find, holds, limiter)).status for _ in range(5)]
check("the first three get through", codes[:3] == [200, 200, 200], f"-> {codes}")
check("the rest are throttled", codes[3:] == [429, 429], f"-> {codes}")
other = run(answer_check("another-key-entirely", "900", find, holds, limiter))
check("a different key has its own allowance", other.status == 403,
      f"-> {other.status} (403 = got past the limiter and was then rejected)")
check("throttling does not leak either", other.body.get("verified") is False)


# ── The relying side: reading an answer ───────────────────────────────────────
check("a yes is a yes", _read_check(200, b'{"verified": true}').outcome is Outcome.VERIFIED)
check("a no is a no", _read_check(200, b'{"verified": false}').outcome is Outcome.NOT_VERIFIED)
check("403 is its own outcome",
      _read_check(403, b'{"verified": false}').outcome is Outcome.KEY_REJECTED)
check("403 counts as a broken pairing", _read_check(403, b"{}").pairing_broken)
check("429 is its own outcome", _read_check(429, b"{}").outcome is Outcome.RATE_LIMITED)
check("500 is unreachable", _read_check(500, b"").outcome is Outcome.UNREACHABLE)
check("garbage is a bad response",
      _read_check(200, b"<html>").outcome is Outcome.BAD_RESPONSE)
check("a JSON array is a bad response",
      _read_check(200, b"[1,2]").outcome is Outcome.BAD_RESPONSE)
check("an oversized body is refused",
      _read_check(200, b'{"verified": true}' + b" " * (64 * 1024)).outcome
      is Outcome.BAD_RESPONSE)

# Fail closed: anything that is not literally `true` is a no. A partner answering "yes",
# 1 or "true" is not answering this protocol, and guessing generously here is the one
# guess that must never be made.
for sneaky in (b'{"verified": "true"}', b'{"verified": 1}', b'{"verified": "yes"}',
               b'{"verified": [true]}', b'{}', b'{"ok": true}'):
    check(f"not a clear yes: {sneaky!r}",
          _read_check(200, sneaky).outcome is Outcome.NOT_VERIFIED)

check("info is read", _read_info(200, b'{"ok": true, "server": "S", "roles": ["A"]}')
      == {"server": "S", "roles": ["A"]})
check("info without ok is dropped", _read_info(200, b'{"server": "S"}') is None)
check("info on a 403 is dropped", _read_info(403, b'{"ok": true}') is None)
check("info survives a missing role list",
      _read_info(200, b'{"ok": true}') == {"server": "", "roles": []})


# ── The relying side: addresses ───────────────────────────────────────────────
for inside in ("http://127.0.0.1:8080", "http://localhost/x", "https://10.0.0.5",
               "http://192.168.1.1", "http://[::1]/", "http://169.254.169.254/latest"):
    check(f"refused, points inside: {inside}", not is_public_url(inside))

for nonsense in ("", "ftp://example.com", "file:///etc/passwd", "not a url",
                 "javascript:alert(1)", "https://"):
    check(f"refused, not http(s) to a host: {nonsense!r}", not is_public_url(nonsense))

# And the same check has to hold through the client, not just in the helper.
r = ask_partner_sync("http://127.0.0.1:9/coop", "key", "900")
check("the client refuses an inside address", r.outcome is Outcome.REFUSED_ADDRESS)
check("a refused address counts as a broken pairing", r.pairing_broken)
check("and it is not verified", not r.verified)

print(f"\n{passed} checks, {len(failed)} failed")
for f in failed:
    print(f"  x {f}")
sys.exit(1 if failed else 0)
