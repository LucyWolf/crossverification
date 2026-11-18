"""The relying side of CrossVerification — asking a partner.

This half is where the mistakes are expensive, so it is written to be boring:

* every unclear outcome is a **no** (SPEC.md §6),
* the address is checked against private networks before anything is sent (§3),
* no redirects, a size cap and a timeout,
* and a `403` is reported as its own outcome, because it is the one status that says
  something about the PAIRING rather than about the person.

Two entry points, same checks: `ask_partner` for an asyncio bot (needs `aiohttp`, which any
discord.py bot already has) and `ask_partner_sync` for everything else (standard library
only). Neither raises on a failed request; they return an outcome.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Optional

__all__ = ["Outcome", "Result", "ask_partner", "ask_partner_sync",
           "fetch_info", "is_public_url", "MAX_RESPONSE", "TIMEOUT"]

#: Nothing this protocol defines comes close to this. See SPEC.md §3.
MAX_RESPONSE = 64 * 1024
#: Seconds. A partner that needs longer is down as far as a joining member is concerned.
TIMEOUT = 8


class Outcome(str, Enum):
    """Why the answer turned out the way it did.

    Only VERIFIED grants anything. The rest exist so an admin can be told WHY a pairing is
    not working - "no" alone sends people looking in the wrong place.
    """

    VERIFIED = "verified"             # a clear yes
    NOT_VERIFIED = "not_verified"     # a clear no
    KEY_REJECTED = "key_rejected"     # 403: the key is unknown or revoked - the pairing is broken
    RATE_LIMITED = "rate_limited"     # 429: we are asking too often
    UNREACHABLE = "unreachable"       # network, timeout, TLS, bad status
    BAD_RESPONSE = "bad_response"     # answered, but not with something this protocol defines
    REFUSED_ADDRESS = "refused_address"   # points into a private network, or is not http(s)


@dataclass(frozen=True)
class Result:
    outcome: Outcome
    detail: str = ""

    @property
    def verified(self) -> bool:
        """The only property worth branching on when granting something."""
        return self.outcome is Outcome.VERIFIED

    @property
    def pairing_broken(self) -> bool:
        """Worth telling an admin about; everything else may just be a bad minute."""
        return self.outcome in (Outcome.KEY_REJECTED, Outcome.REFUSED_ADDRESS)


def is_public_url(url: str) -> bool:
    """Whether this address is safe for the server itself to open.

    Whoever configures a pairing hands the server a URL. Without this check that URL could
    just as well be `http://127.0.0.1:8080` or a cloud provider's metadata endpoint - the
    server sits inside a network and reaches things the person asking never could, so the
    pairing form would double as a scanner for the issuer's own network.

    EVERY address the name resolves to is checked, not just the first: a name answering with
    one public and one loopback address would otherwise slip through on the public one.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            return False
    return True


def _endpoint(base_url: str, path: str) -> Optional[str]:
    base = (base_url or "").strip().rstrip("/")
    if not base or not is_public_url(base):
        return None
    return f"{base}{path}"


def _read_check(status: int, raw: bytes) -> Result:
    """One place where a response becomes an outcome - shared by both clients.

    Kept separate from the HTTP so it can be tested without a network, which is also why
    every branch below is reachable from the test suite.
    """
    if status == 403:
        return Result(Outcome.KEY_REJECTED, "partner rejected the key")
    if status == 429:
        return Result(Outcome.RATE_LIMITED, "asking too often")
    if status != 200:
        return Result(Outcome.UNREACHABLE, f"HTTP {status}")
    if len(raw) > MAX_RESPONSE:
        return Result(Outcome.BAD_RESPONSE, "response too large")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return Result(Outcome.BAD_RESPONSE, "not JSON")
    if not isinstance(data, dict):
        return Result(Outcome.BAD_RESPONSE, "not an object")
    # `is True` and not a truthy check: a partner answering "verified": "no" or 1 is not
    # answering this protocol, and guessing in the generous direction is the one guess that
    # must never be made here.
    if data.get("verified") is True:
        return Result(Outcome.VERIFIED)
    return Result(Outcome.NOT_VERIFIED)


def _read_info(status: int, raw: bytes) -> Optional[dict]:
    if status != 200 or len(raw) > MAX_RESPONSE:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    roles = data.get("roles")
    return {
        "server": str(data.get("server") or "")[:200],
        "roles": [str(r)[:100] for r in roles][:100] if isinstance(roles, list) else [],
    }


async def ask_partner(base_url: str, key: str, user_id, *,
                      timeout: int = TIMEOUT) -> Result:
    """Ask one partner whether this user counts as verified there. Never raises."""
    url = _endpoint(base_url, "/coop/check")
    if not url:
        return Result(Outcome.REFUSED_ADDRESS, "not a public http(s) address")
    try:
        import aiohttp
    except ImportError:          # pragma: no cover - depends on the host bot
        raise RuntimeError(
            "ask_partner needs aiohttp; use ask_partner_sync for a bot without it") from None
    try:
        conf = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=conf) as session:
            # allow_redirects=False: a pairing points at ONE address. A redirect is either a
            # misconfiguration or somebody steering the key somewhere else.
            async with session.post(url, data={"key": key, "user_id": str(user_id)},
                                    allow_redirects=False) as response:
                raw = await response.content.read(MAX_RESPONSE + 1)
                return _read_check(response.status, raw)
    except Exception as err:
        return Result(Outcome.UNREACHABLE, type(err).__name__)


def ask_partner_sync(base_url: str, key: str, user_id, *,
                     timeout: int = TIMEOUT) -> Result:
    """Same question, standard library only. Never raises."""
    url = _endpoint(base_url, "/coop/check")
    if not url:
        return Result(Outcome.REFUSED_ADDRESS, "not a public http(s) address")
    import urllib.error
    import urllib.request

    body = urllib.parse.urlencode({"key": key, "user_id": str(user_id)}).encode()
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "crossverification/1.0"})

    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            return _read_check(response.status, response.read(MAX_RESPONSE + 1))
    except urllib.error.HTTPError as err:
        try:
            raw = err.read(MAX_RESPONSE + 1)
        except Exception:
            raw = b""
        return _read_check(err.code, raw)
    except Exception as err:
        return Result(Outcome.UNREACHABLE, type(err).__name__)


async def fetch_info(base_url: str, key: str, *, timeout: int = TIMEOUT) -> Optional[dict]:
    """What the partner shares, for the setup screen. None when it cannot be had."""
    url = _endpoint(base_url, "/coop/info")
    if not url:
        return None
    try:
        import aiohttp
    except ImportError:          # pragma: no cover
        raise RuntimeError("fetch_info needs aiohttp") from None
    try:
        conf = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=conf) as session:
            async with session.post(url, data={"key": key},
                                    allow_redirects=False) as response:
                raw = await response.content.read(MAX_RESPONSE + 1)
                return _read_info(response.status, raw)
    except Exception:
        return None
