"""Tests for MT5 identity tagging (FX Phase 0, Step 4)."""

from __future__ import annotations

import uuid

import pytest

from mt5_bridge.identity import MAX_COMMENT_LENGTH, build_mt5_comment, short_order_tag


def test_short_tag_is_deterministic():
    coid = str(uuid.uuid4())
    assert short_order_tag(coid) == short_order_tag(coid)


def test_short_tag_differs_for_different_ids():
    assert short_order_tag("a") != short_order_tag("b")


def test_comment_fits_within_mt5_limit():
    coid = str(uuid.uuid4())
    comment = build_mt5_comment(coid)
    assert len(comment) <= MAX_COMMENT_LENGTH


def test_comment_has_recognizable_prefix():
    comment = build_mt5_comment(str(uuid.uuid4()))
    assert comment.startswith("TIA:")


def test_comment_is_stable_for_same_client_order_id():
    coid = "fixed-id-123"
    assert build_mt5_comment(coid) == build_mt5_comment(coid)
