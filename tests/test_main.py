"""Tests for main module."""

from mcp_zero.main import run


def test_run(capsys):
    run()
    captured = capsys.readouterr()
    assert captured.out.strip() == "mcp-zero"
