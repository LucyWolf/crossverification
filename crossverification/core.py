"""The issuer side of CrossVerification — answering a partner's questions.

Framework-agnostic on purpose. This module knows nothing about FastAPI, Flask, discord.py or
any database; it takes the two fields out of a request and two callbacks that your bot
supplies, and hands back a status code and a body. Wiring it into a web framework is six
lines, and those six lines are the only part you have to write yourself.

The reason for that split: the hard part of this protocol is not the HTTP. It is the handful
of decisions that are easy to get subtly wrong — answering an unknown key differently from
an unknown user, forgetting the rate limit, leaking whether somebody is a member at all.
Those live here, in one place, and are covered by the tests.

See SPEC.md for the protocol itself.
"""

from __future__ import annotations

import hashlib
import inspect
import secrets
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Optional, Union

__all__ = [
    "Partner", "Answer", "RateLimiter",
    "new_key", "key_hash",
    "answer_check", "answer_info",
]

#: Requests per key per minute an issuer accepts by default. See SPEC.md §5.
DEFAULT_RATE_LIMIT = 60


@dataclass(frozen=True)
class Partner:
    """One pairing, as your bot knows it.

    `shared_roles` holds whatever identifies the roles in YOUR system — Discord role ids as
    strings in most cases. This module never interprets them; it only hands them back to
    your `holds_role` callback and uses `shared_role_names` for the info endpoint.
    """

    name: str = ""
    shared_roles: frozenset = field(default_factory=frozenset)
    shared_role_names: tuple = ()
    server_name: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class Answer:
    """What to send back: an HTTP status and a JSON body."""

    status: int
    body: dict

    @property
    def ok(self) -> bool:
        return self.status == 200


# A lookup may be sync or async - a bot built on asyncio will want async, a small script
# will not. Both are accepted and awaited only when needed.
FindPartner = Callable[[str], Union[Optional[Partner], Awaitable[Optional[Partner]]]]
HoldsRole = Callable[[str, Partner], Union[bool, Awaitable[bool]]]


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def new_key(bytes_: int = 32) -> str:
    """A fresh pairing key. Unguessable, URL-safe, handed to the partner once."""
    return secrets.token_urlsafe(bytes_)


def key_hash(raw: str) -> str:
    """What to store instead of the key itself.

    A pairing key is a long random secret that is only ever COMPARED, never read back - so
    storing the hash costs nothing and means a leaked database does not leak the keys. No
    stretching: that protects guessable secrets, and this one is not guessable.
    """
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


class RateLimiter:
    """Requests per key per minute, in memory.

    Counted per KEY, not per address: a partner behind a changing address is still one
    partner, and a shared address is still several. Good enough for a single process; behind
    several workers, put a shared counter here instead - the interface is one method.
    """

    def __init__(self, per_minute: int = DEFAULT_RATE_LIMIT, max_keys: int = 500) -> None:
        self.per_minute = per_minute
        self.max_keys = max_keys
        self._seen: dict = {}

    def hit(self, key_digest: str) -> bool:
        """True when this key has used up its allowance. Counts the request either way."""
        now = time.monotonic()
        window = self._seen.setdefault(key_digest, [])
        while window and now - window[0] > 60:
            window.pop(0)
        if len(window) >= self.per_minute:
            return True
        window.append(now)
        if len(self._seen) > self.max_keys:
            for stale in [k for k, v in self._seen.items()
                          if not v or now - v[-1] > 300]:
                self._seen.pop(stale, None)
        return False


def _valid_user_id(raw: str) -> bool:
    """A Discord snowflake, as far as this protocol cares: digits, and not absurdly long."""
    return bool(raw) and raw.isdigit() and len(raw) <= 25


async def _resolve(find_partner: FindPartner, key: str) -> Optional[Partner]:
    partner = await _maybe_await(find_partner(key))
    if partner is None or not getattr(partner, "enabled", True):
        return None
    return partner


async def answer_check(
    key: str,
    user_id: str,
    find_partner: FindPartner,
    holds_role: HoldsRole,
    limiter: Optional[RateLimiter] = None,
) -> Answer:
    """`POST /coop/check` — does this user count as verified here?

    `find_partner(key)` returns the Partner for a key, or None. Hash the key yourself and
    look the hash up; `key_hash` is right here.

    `holds_role(user_id, partner)` returns whether that user currently holds any of the
    roles this pairing shares. Not "did they ever" - a verification that was taken away is
    not a verification.

    Note what is NOT in any answer: no name, no role, no sign of whether the person exists
    here. An unknown key gets the same body as an unknown person, so the endpoint cannot be
    used to tell valid keys from invalid ones. See SPEC.md §4.1.
    """
    key = (key or "").strip()
    user_id = (user_id or "").strip()
    if not key or not _valid_user_id(user_id):
        return Answer(400, {"verified": False})

    if limiter is not None and limiter.hit(key_hash(key)):
        return Answer(429, {"verified": False, "error": "too many requests"})

    partner = await _resolve(find_partner, key)
    if partner is None:
        return Answer(403, {"verified": False})

    # A pairing that shares nothing answers no. Not an error: somebody set it up and has
    # not picked the roles yet, and until they do there is nothing to vouch for.
    if not partner.shared_roles:
        return Answer(200, {"verified": False})

    verified = bool(await _maybe_await(holds_role(user_id, partner)))
    return Answer(200, {"verified": verified})


async def answer_info(
    key: str,
    find_partner: FindPartner,
    limiter: Optional[RateLimiter] = None,
) -> Answer:
    """`POST /coop/info` — who are you, and which roles does this pairing share?

    For setup only. The other side's admin sees what is actually shared and decides what to
    grant for it, instead of guessing what a role over here is called.

    Returned are role NAMES and the server name - never ids, never the other roles, never
    anything about members.
    """
    key = (key or "").strip()
    if not key:
        return Answer(400, {"ok": False})

    if limiter is not None and limiter.hit(key_hash(key)):
        return Answer(429, {"ok": False, "error": "too many requests"})

    partner = await _resolve(find_partner, key)
    if partner is None:
        return Answer(403, {"ok": False})

    return Answer(200, {
        "ok": True,
        "server": partner.server_name or partner.name or "",
        "roles": list(partner.shared_role_names),
    })


def shared_with(member_roles: Iterable, partner: Partner) -> bool:
    """A ready-made `holds_role` body: does any role of this member appear in the pairing?

    Both sides are compared as strings, because a Discord role id is a 64-bit number that
    arrives as a string about as often as an int, and `"123" != 123` is the kind of bug that
    silently turns every answer into a no.
    """
    have = {str(r) for r in member_roles}
    return bool(have & {str(r) for r in partner.shared_roles})
