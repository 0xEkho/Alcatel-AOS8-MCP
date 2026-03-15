"""Regression tests for the write_guard architectural contract.

Objectives
----------
1. Verify that ``aos_poe_restart`` is NOT registered as an MCP tool
   (it has been intentionally removed from ``poe.py``).
2. Verify that ``aos_poe_reboot_request`` IS registered as an MCP tool
   (human approval workflow via Teams).
3. Verify that :func:`write_guard` returns an error string without
   ever raising an exception (MCP best-practices compliance).

These tests act as a safety net: any accidental re-introduction of
``aos_poe_restart`` or any other direct WRITE tool will be detected
immediately.

Strategy
--------
* Isolated FastMCP fixtures — one instance per tool module.
* No SSH, no HTTP: tests only instantiate MCP instances and call
  ``list_tools()``; no command execution is required.
* ``write_guard`` is tested in pure isolation (direct import).
"""
import pytest
from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_with_poe():
    """Fresh FastMCP instance with only the poe tools registered."""
    instance = FastMCP("test-write-guard-poe")
    from mcp_server.tools.poe import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_with_poe_approval():
    """Fresh FastMCP instance with only the poe_approval tools registered."""
    instance = FastMCP("test-write-guard-poe-approval")
    from mcp_server.tools.poe_approval import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def all_tool_names_combined():
    """Set of all tool names registered on a fully combined instance.

    Simulates the real ``server.py`` registration by loading both
    relevant modules (poe + poe_approval) on the same instance.
    """
    instance = FastMCP("test-write-guard-combined")
    from mcp_server.tools.poe import register_tools as reg_poe
    from mcp_server.tools.poe_approval import register_tools as reg_approval
    reg_poe(instance)
    reg_approval(instance)
    return instance


# ---------------------------------------------------------------------------
# 1. Regression: aos_poe_restart must NOT exist in poe.py
# ---------------------------------------------------------------------------


async def test_aos_poe_restart_absent_from_poe_module(mcp_with_poe):
    """aos_poe_restart must NOT be registered in the poe module.

    Regression: this tool was intentionally removed from poe.py to enforce
    the use of the aos_poe_reboot_request approval workflow.
    Its reappearance would be a write_guard bypass.
    """
    tool_names = {t.name for t in await mcp_with_poe.list_tools()}
    assert "aos_poe_restart" not in tool_names, (
        "REGRESSION DETECTED: 'aos_poe_restart' has been re-introduced in poe.py. "
        "This direct WRITE tool must remain removed — use aos_poe_reboot_request instead."
    )


async def test_aos_poe_restart_absent_from_combined_instance(all_tool_names_combined):
    """aos_poe_restart must NOT appear on a multi-module instance.

    Verifies that no module (poe or poe_approval) exposes the banned tool,
    even when both are loaded together.
    """
    tool_names = {t.name for t in await all_tool_names_combined.list_tools()}
    assert "aos_poe_restart" not in tool_names, (
        "REGRESSION DETECTED: 'aos_poe_restart' is present in one of the "
        "loaded modules. This direct WRITE tool must never be registered."
    )


# ---------------------------------------------------------------------------
# 2. Regression: aos_poe_reboot_request MUST exist in poe_approval.py
# ---------------------------------------------------------------------------


async def test_aos_poe_reboot_request_present_in_poe_approval_module(mcp_with_poe_approval):
    """aos_poe_reboot_request MUST be registered in the poe_approval module.

    It is the only legitimate path to restart PoE — it enforces human
    validation via Teams before any execution on the switch.
    """
    tool_names = {t.name for t in await mcp_with_poe_approval.list_tools()}
    assert "aos_poe_reboot_request" in tool_names, (
        "aos_poe_reboot_request not found in poe_approval. "
        "This tool is the mandatory approval workflow for any PoE reboot."
    )


async def test_aos_poe_reboot_request_present_in_combined_instance(all_tool_names_combined):
    """aos_poe_reboot_request MUST be available on a multi-module instance.

    Verifies that the approval workflow is accessible when all modules are
    loaded together (as in production).
    """
    tool_names = {t.name for t in await all_tool_names_combined.list_tools()}
    assert "aos_poe_reboot_request" in tool_names, (
        "aos_poe_reboot_request is missing from the combined instance. "
        "Check that poe_approval is registered in server.py."
    )


# ---------------------------------------------------------------------------
# 3. write_guard() — never raises an exception, always returns a string
# ---------------------------------------------------------------------------


def test_write_guard_returns_string_not_exception():
    """write_guard() must return a str, never raise an exception.

    MCP compliance: business errors are returned in the result,
    not propagated as exceptions.
    """
    from mcp_server.tools._write_guard import write_guard

    result = write_guard("some_write_tool")
    assert isinstance(result, str), (
        f"write_guard must return a str, got: {type(result)}"
    )


def test_write_guard_contains_tool_name():
    """write_guard() must include the tool name in its error message.

    The LLM must be able to identify which tool was blocked and why.
    """
    from mcp_server.tools._write_guard import write_guard

    result = write_guard("aos_poe_restart")
    assert "aos_poe_restart" in result, (
        "The write_guard message must mention the name of the blocked tool."
    )


def test_write_guard_mentions_approved_workflow():
    """write_guard() must mention the alternative approval workflow.

    The LLM must be directed toward aos_poe_reboot_request rather than being
    blocked without any explanation of the alternative.
    """
    from mcp_server.tools._write_guard import write_guard

    result = write_guard("aos_poe_restart")
    assert "aos_poe_reboot_request" in result, (
        "The write_guard message must indicate aos_poe_reboot_request as the alternative."
    )


def test_write_guard_never_raises_on_arbitrary_tool_name():
    """write_guard() must not raise an exception regardless of the name passed.

    Verifies robustness with atypical names (empty, special characters).
    """
    from mcp_server.tools._write_guard import write_guard

    for tool_name in ("", "tool/with/slashes", "tool with spaces", "outil-àçé", "x" * 200):
        try:
            result = write_guard(tool_name)
            assert isinstance(result, str), (
                f"write_guard('{tool_name}') must return a str."
            )
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"write_guard('{tool_name}') raised an unexpected exception: {exc!r}"
            )
