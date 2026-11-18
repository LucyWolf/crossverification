"""CrossVerification — let one Discord bot honour another one's vetting.

    from crossverification import answer_check, Partner, key_hash, new_key   # issuer
    from crossverification import ask_partner, Outcome                       # relying party

The protocol is in SPEC.md; this package is its reference implementation. Both halves work
without each other, and neither one needs this package to be on the other side — anything
that follows the spec will do.
"""

from .core import (                     # noqa: F401
    DEFAULT_RATE_LIMIT,
    Answer,
    Partner,
    RateLimiter,
    answer_check,
    answer_info,
    key_hash,
    new_key,
    shared_with,
)
from .client import (                   # noqa: F401
    MAX_RESPONSE,
    TIMEOUT,
    Outcome,
    Result,
    ask_partner,
    ask_partner_sync,
    fetch_info,
    is_public_url,
)

#: The protocol version this implementation speaks. See SPEC.md §9.
PROTOCOL_VERSION = "1.0"
__version__ = "1.0.0"
