"""Strict, strategy-neutral official monetary-policy event primitives.

Phase 5K deliberately models provenance and timing only.  It contains no bar,
price, signal, execution, or PnL dependency.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import html
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo


class ProvenanceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISSING_OFFICIAL_TIME = "MISSING_OFFICIAL_TIME"
    MISSING_POLICY_VALUE = "MISSING_POLICY_VALUE"
    UNSCHEDULED_OUT_OF_SCOPE = "UNSCHEDULED_OUT_OF_HYPOTHESIS_SCOPE"


class ChangeDirection(str, Enum):
    WIDENS = "WIDENS"
    NARROWS = "NARROWS"
    UNCHANGED = "UNCHANGED"


class BoJRegime(str, Enum):
    NEGATIVE_RATE = "BOJ_NEGATIVE_RATE_REGIME"
    TRANSITION = "REGIME_TRANSITION"
    OVERNIGHT_GUIDELINE = "BOJ_OVERNIGHT_RATE_REGIME"


def utc_from_local(value: datetime, timezone_name: str) -> datetime:
    """Attach an IANA source timezone and normalize deterministically to UTC."""
    if value.tzinfo is not None:
        raise ValueError("local source datetime must be naive")
    return value.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc)


def signed_change(old: Decimal, new: Decimal) -> tuple[Decimal, ChangeDirection]:
    change = new - old
    return change, ChangeDirection.WIDENS if change > 0 else ChangeDirection.NARROWS if change < 0 else ChangeDirection.UNCHANGED


def differential_change(old_fed: Decimal, old_boj: Decimal, new_fed: Decimal, new_boj: Decimal) -> tuple[Decimal, Decimal, Decimal, ChangeDirection]:
    """Return old differential, new differential, signed delta and its label."""
    old, new = old_fed - old_boj, new_fed - new_boj
    delta, direction = signed_change(old, new)
    return old, new, delta, direction


def boj_regime(meeting_date: str) -> BoJRegime:
    """Classify the official March 19, 2024 framework boundary without a splice."""
    if meeting_date < "2024-03-19": return BoJRegime.NEGATIVE_RATE
    if meeting_date == "2024-03-19": return BoJRegime.TRANSITION
    return BoJRegime.OVERNIGHT_GUIDELINE


def regime_safe_differential_direction(old_regime: BoJRegime, new_regime: BoJRegime, old_fed: Decimal, old_boj: Decimal, new_fed: Decimal, new_boj: Decimal) -> ChangeDirection | BoJRegime:
    """Never assign a numeric differential direction across BoJ regimes."""
    if old_regime is not new_regime: return BoJRegime.TRANSITION
    return differential_change(old_fed, old_boj, new_fed, new_boj)[3]


def strict_json(value: object) -> bytes:
    def clean(item: object) -> object:
        if isinstance(item, Decimal): return str(item)
        if isinstance(item, datetime): return item.isoformat()
        if isinstance(item, Enum): return item.value
        if isinstance(item, dict): return {str(k): clean(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)): return [clean(v) for v in item]
        if isinstance(item, float) and (item != item or item in (float("inf"), float("-inf"))): raise ValueError("NaN/Infinity forbidden")
        return item
    return json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: object) -> str:
    return hashlib.sha256(strict_json(value)).hexdigest()


_RELEASE_BLOCK = re.compile(r"Release dates and times:</dt>(.*?)</dl>", re.I | re.S)
_RELEASE_LINE = re.compile(r"^\s*(.+?)\s+--\s+.*?\s*at\s+(\d{1,2}:\d{2})\s*$", re.I | re.M)


def parse_boj_release_time(source_html: bytes) -> tuple[str, str]:
    """Extract the sole decision release title/time from a BoJ HTML document.

    The source section can also name a framework-change document rather than a
    literal ``Statement on Monetary Policy``.  Missing or competing decision
    entries are errors, never an inferred timestamp.
    """
    text = html.unescape(source_html.decode("utf-8", errors="strict"))
    block = _RELEASE_BLOCK.search(text)
    if block is None: raise ValueError("MISSING_OFFICIAL_TIME: release section absent")
    plain = re.sub(r"<[^>]+>", "", block.group(1))
    candidates = [(re.sub(r"\s+", " ", title).strip(), time) for title, time in _RELEASE_LINE.findall(plain)]
    candidates = [item for item in candidates if item[0].startswith(("Statement on Monetary Policy", "Changes in the Monetary Policy Framework", "Change in the Guideline for Money Market Operations"))]
    if len(candidates) != 1: raise ValueError(f"AMBIGUOUS_OFFICIAL_TIME: decision release candidates={len(candidates)}")
    return candidates[0]


def build_boj_v2(source_dir: Path, retrieved_at: datetime) -> dict[str, object]:
    """Build provenance-only v2 records from archived official BoJ HTML bytes."""
    if retrieved_at.utcoffset() != timezone.utc.utcoffset(None): raise ValueError("retrieved_at must be UTC")
    events = []
    for path in sorted(source_dir.glob("k*a.htm")):
        stamp = path.stem[1:7]
        date = datetime.strptime(stamp, "%y%m%d")
        title, local_time = parse_boj_release_time(path.read_bytes())
        local = datetime(date.year, date.month, date.day, *map(int, local_time.split(":")))
        instrument = "short-term-policy-interest-rate" if date.date() < datetime(2024, 3, 19).date() else "uncollateralized-overnight-call-rate-guideline" if date.date() > datetime(2024, 3, 19).date() else "policy-framework-transition"
        events.append({"event_id": f"boj-{date:%Y-%m-%d}", "meeting_end_date": f"{date:%Y-%m-%d}", "source_document_title": title, "official_release_timestamp_local": local.isoformat(timespec="minutes"), "official_release_timezone": "Asia/Tokyo", "official_release_timestamp_utc": utc_from_local(local, "Asia/Tokyo").isoformat(), "source_url": f"https://www.boj.or.jp/en/mopo/mpmdeci/state_{date:%Y}/k{stamp}a.htm", "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_retrieved_at": retrieved_at.isoformat(), "timestamp_status": "VERIFIED_OFFICIAL_TIME", "policy_instrument": instrument, "scalar_status": "NOT_FROZEN_REGIME_COHERENCE_REVIEW_REQUIRED"})
    return {"dataset_version": "phase5k_policy_events_v2", "central_bank": "BOJ", "events": events, "event_count": len(events), "timestamp_summary": {"verified": len(events), "missing": 0, "ambiguous": 0}, "scalar_status": "BLOCKED_PENDING_REGIME_COHERENCE_DECISION"}


@dataclass(frozen=True)
class PolicyRateDecisionEvent:
    central_bank: str
    event_id: str
    meeting_start_date: str
    meeting_end_date: str
    scheduled: bool
    official_release_timestamp_local: str | None
    official_release_timezone: str | None
    official_release_timestamp_utc: datetime | None
    source_url: str
    source_document_title: str
    source_document_date: str
    source_retrieved_at: datetime
    policy_instrument: str
    old_policy_value: Decimal | None
    new_policy_value: Decimal | None
    change_value: Decimal | None
    change_direction: ChangeDirection | None
    effective_timestamp: datetime | None
    effective_convention: str
    source_identity_sha256: str
    provenance_status: ProvenanceStatus

    def __post_init__(self) -> None:
        if not self.central_bank or not self.event_id or not self.source_url: raise ValueError("event identity/source required")
        if self.official_release_timestamp_utc is not None and self.official_release_timestamp_utc.utcoffset() != timezone.utc.utcoffset(None): raise ValueError("release timestamp must be UTC-aware")
        if self.source_retrieved_at.utcoffset() != timezone.utc.utcoffset(None): raise ValueError("retrieval timestamp must be UTC-aware")
        if self.provenance_status is ProvenanceStatus.VERIFIED:
            if self.official_release_timestamp_utc is None or self.old_policy_value is None or self.new_policy_value is None: raise ValueError("verified event requires official time and policy values")
        if (self.old_policy_value is None) != (self.new_policy_value is None): raise ValueError("policy values must be jointly present or absent")

    def to_dict(self) -> dict[str, object]:
        return json.loads(strict_json(asdict(self)))


def signal_ready(event: PolicyRateDecisionEvent) -> bool:
    """Future signal tooling must fail closed on any provenance ambiguity."""
    return event.scheduled and event.provenance_status is ProvenanceStatus.VERIFIED
