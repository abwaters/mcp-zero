"""Tests for KeyBuilder — Redis key namespacing."""

from __future__ import annotations

from mcp_zero.analytics.keys import KeyBuilder


class TestKeyBuilder:
    def setup_method(self):
        self.kb = KeyBuilder("mcpgw", "production", "gw1")

    def test_base_prefix(self):
        assert self.kb.base == "mcpgw:production:gw1"

    def test_bucket_id_computation(self):
        # epoch 60000 / 60 = 1000
        assert self.kb.bucket_id(60, epoch=60000.0) == 1000
        # epoch 119 / 60 = 1 (integer division)
        assert self.kb.bucket_id(60, epoch=119.0) == 1

    def test_bucket_id_uses_current_time_when_none(self):
        bid = self.kb.bucket_id(60)
        assert isinstance(bid, int)
        assert bid > 0

    def test_bucket_key(self):
        key = self.kb.bucket_key("tool_calls", 12345)
        assert key == "mcpgw:production:gw1:b:12345:tool_calls"

    def test_bucket_key_different_metrics(self):
        assert self.kb.bucket_key("denials", 1) == "mcpgw:production:gw1:b:1:denials"
        assert self.kb.bucket_key("redactions", 2) == "mcpgw:production:gw1:b:2:redactions"

    def test_registry_key(self):
        assert self.kb.registry_key() == "mcpgw:gateways"

    def test_info_key(self):
        assert self.kb.info_key() == "mcpgw:gw:production:gw1:info"

    def test_different_environments_produce_different_keys(self):
        kb_staging = KeyBuilder("mcpgw", "staging", "gw1")
        assert self.kb.bucket_key("tool_calls", 1) != kb_staging.bucket_key("tool_calls", 1)
        assert self.kb.info_key() != kb_staging.info_key()

    def test_different_gateways_produce_different_keys(self):
        kb_other = KeyBuilder("mcpgw", "production", "gw2")
        assert self.kb.bucket_key("tool_calls", 1) != kb_other.bucket_key("tool_calls", 1)
        assert self.kb.info_key() != kb_other.info_key()
        # Registry key is shared across gateways (same prefix)
        assert self.kb.registry_key() == kb_other.registry_key()
