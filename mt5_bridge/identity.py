"""TradingIA identity inside MT5: magic number + comment tag (FX Phase 0, Step 4).

MT5 gives an EA/system exactly two free-form identity fields on an
order/position: `magic` (an integer) and `comment` (a short string, with
a broker-enforced length limit that varies but is commonly ~31 chars).
Neither is itself a secure identity mechanism -- both can collide with
another EA's choices -- so this module documents that TradingIA's
identity is the COMBINATION of magic + comment tag + the full mapping
kept in `mt5_bridge/store.py`'s idempotency table, never any single
field alone (see Step 4 request section 9).

`client_order_id` (typically a UUID, ~36 chars) does not fit in MT5's
comment field, so `short_order_tag` derives a short, deterministic tag
from it (first 8 hex chars of its SHA-256) and prefixes it with "TIA:"
for at-a-glance recognizability in the MT5 terminal's own order history.
The full `client_order_id` <-> tag mapping lives in SQLite
(`idempotency.client_order_id` is the real key; the tag is only what
gets embedded in MT5's comment), so a short tag collision (extremely
unlikely at 8 hex chars, but not impossible) does not create an
identity confusion -- reconciliation logic keys off `client_order_id`
in the local DB, and only uses the comment tag as one corroborating
signal among several (see `mt5_bridge/reconciliation.py`).
"""

from __future__ import annotations

import hashlib

COMMENT_PREFIX = "TIA:"
_TAG_HEX_LENGTH = 8
MAX_COMMENT_LENGTH = 31  # conservative; several brokers truncate beyond this


def short_order_tag(client_order_id: str) -> str:
    digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()
    return digest[:_TAG_HEX_LENGTH]


def build_mt5_comment(client_order_id: str) -> str:
    comment = f"{COMMENT_PREFIX}{short_order_tag(client_order_id)}"
    if len(comment) > MAX_COMMENT_LENGTH:
        raise ValueError(f"generated MT5 comment {comment!r} exceeds {MAX_COMMENT_LENGTH} chars")
    return comment
