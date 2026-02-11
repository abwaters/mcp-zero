"""Tests for KeyBuilder — hierarchical Redis key namespacing."""

from __future__ import annotations

from mcp_zero.analytics.keys import KeyBuilder


class TestKeyBuilder:
    def setup_method(self):
        self.kb = KeyBuilder("mcpgw", "production", "gw1")

    def test_gateway_base(self):
        assert self.kb.gateway_base == "mcpgw:gw:production:gw1"

    def test_bucket_id_computation(self):
        assert self.kb.bucket_id(60, epoch=60000.0) == 1000
        assert self.kb.bucket_id(60, epoch=119.0) == 1

    def test_bucket_id_uses_current_time_when_none(self):
        bid = self.kb.bucket_id(60)
        assert isinstance(bid, int)
        assert bid > 0

    def test_bucket_key_hierarchical(self):
        key = self.kb.bucket_key("calls", "tool", 12345)
        assert key == "mcpgw:gw:production:gw1:b:12345:calls:tool"

    def test_bucket_key_latency(self):
        assert (
            self.kb.bucket_key("latency", "sum", 1)
            == "mcpgw:gw:production:gw1:b:1:latency:sum"
        )
        assert (
            self.kb.bucket_key("latency", "max", 1)
            == "mcpgw:gw:production:gw1:b:1:latency:max"
        )

    def test_bucket_key_denials(self):
        assert (
            self.kb.bucket_key("denials", "tool", 1)
            == "mcpgw:gw:production:gw1:b:1:denials:tool"
        )
        assert (
            self.kb.bucket_key("denials", "reason", 1)
            == "mcpgw:gw:production:gw1:b:1:denials:reason"
        )

    def test_bucket_key_redactions(self):
        assert (
            self.kb.bucket_key("redactions", "input", 1)
            == "mcpgw:gw:production:gw1:b:1:redactions:input"
        )
        assert (
            self.kb.bucket_key("redactions", "output", 1)
            == "mcpgw:gw:production:gw1:b:1:redactions:output"
        )
        assert (
            self.kb.bucket_key("redactions", "fail", 1)
            == "mcpgw:gw:production:gw1:b:1:redactions:fail"
        )

    def test_registry_key(self):
        assert self.kb.registry_key() == "mcpgw:registry"

    def test_info_key(self):
        assert self.kb.info_key() == "mcpgw:gw:production:gw1:info"

    def test_idx_envs_key(self):
        assert self.kb.idx_envs_key() == "mcpgw:idx:envs"

    def test_idx_gateways_key(self):
        assert self.kb.idx_gateways_key() == "mcpgw:idx:gw:production"

    def test_registry_member(self):
        assert self.kb.registry_member == "production:gw1"

    def test_different_environments_produce_different_keys(self):
        kb_staging = KeyBuilder("mcpgw", "staging", "gw1")
        assert self.kb.bucket_key("calls", "tool", 1) != kb_staging.bucket_key(
            "calls", "tool", 1
        )
        assert self.kb.info_key() != kb_staging.info_key()
        assert self.kb.idx_gateways_key() != kb_staging.idx_gateways_key()

    def test_different_gateways_produce_different_keys(self):
        kb_other = KeyBuilder("mcpgw", "production", "gw2")
        assert self.kb.bucket_key("calls", "tool", 1) != kb_other.bucket_key(
            "calls", "tool", 1
        )
        assert self.kb.info_key() != kb_other.info_key()
        # Registry and idx:envs are shared across gateways (same prefix)
        assert self.kb.registry_key() == kb_other.registry_key()
        assert self.kb.idx_envs_key() == kb_other.idx_envs_key()
        # idx:gw:{env} is shared across gateways in the same env
        assert self.kb.idx_gateways_key() == kb_other.idx_gateways_key()
