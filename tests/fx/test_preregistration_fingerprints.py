from pathlib import Path

import pytest

from src.fx.research.fingerprints import canonical_document_sha256, canonicalize_self_fingerprinted_document, verify_canonical_document_fingerprint


ROOT = Path(__file__).resolve().parents[2]
COST = "a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c"
STRATEGY = "212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709"


def test_phase5h_frozen_regressions_and_phase5g_convention():
    assert verify_canonical_document_fingerprint(ROOT / "PHASE5H_COST_PREREGISTRATION.md", COST)
    assert verify_canonical_document_fingerprint(ROOT / "PHASE5H_PREREGISTRATION.md", STRATEGY)
    assert canonical_document_sha256(ROOT / "PHASE5G_VIABILITY_PREREGISTRATION.md") == "7bbeab4c4ee8b97aa555b52d13ef8a5b347b6350e3ac46ea1358efd522046e0d"


def test_embedded_value_is_independent_but_every_other_byte_is_sensitive():
    raw = (ROOT / "PHASE5H_PREREGISTRATION.md").read_bytes()
    changed_hash = raw.replace(STRATEGY.encode(), b"f" * 64)
    assert canonicalize_self_fingerprinted_document(raw) == canonicalize_self_fingerprinted_document(changed_hash)
    assert canonicalize_self_fingerprinted_document(raw.replace(b"balance is USD 100", b"balance is USD 101")) != canonicalize_self_fingerprinted_document(raw)
    assert canonicalize_self_fingerprinted_document(raw + b" ") != canonicalize_self_fingerprinted_document(raw)


def test_ambiguity_missing_and_malformed_fail_closed():
    good = b"Preregistration fingerprint: `" + b"a" * 64 + b"`.\n"
    assert b"TO_BE_FILLED_BY_FREEZE_TOOL" in canonicalize_self_fingerprinted_document(good)
    for bad in (b"no field\n", good + good, b"Preregistration fingerprint: `ABC`.\n"):
        with pytest.raises(ValueError):
            canonicalize_self_fingerprinted_document(bad)
