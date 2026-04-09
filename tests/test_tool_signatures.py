"""Verify MCP tool signatures match their META definitions."""

from ramune_shell.mcp.app import mcp
from ramune_shell.mcp.feature import verify_tool_signature
from ramune_shell.mcp.features.exec import META as EXEC_META, exec as exec_feature


def test_exec_signature():
    errors = verify_tool_signature(mcp, EXEC_META)
    assert errors == [], f"exec signature mismatch: {errors}"


def test_all_features_registered():
    """All feature META names should be registered as MCP tools."""
    all_metas = [EXEC_META]  # add more as features grow
    tools = mcp._tool_manager._tools
    for meta in all_metas:
        assert meta["name"] in tools, f"tool '{meta['name']}' not registered"
