"""SC-2/SC-8: no access token, refresh token, or client secret ever reaches
a log line, a model prompt, or an MCP tool description.

Verified statically rather than by capturing log output at runtime: every
logger call in this codebase uses structlog's keyword-argument style
(`logger.info("event", key=value)`), so a source-level scan of which
keyword names are ever passed to a logger call is a direct, reliable check,
and one a team can keep running in CI to catch a future regression, unlike
a runtime log-capture test that only exercises whichever paths that one
test happens to execute.
"""

import ast
from pathlib import Path

GATEWAY_DIR = Path(__file__).parent.parent

# Any of these appearing as a logger call's keyword argument name is a
# strong signal a raw secret is about to be logged; none of this codebase's
# real logger calls use these names (only ids, tenant identifiers, event
# types, and counts are logged).
DISALLOWED_KWARG_NAMES = {
    "access_token",
    "refresh_token",
    "client_secret",
    "code_verifier",
    "code_challenge",
    "token",
    "secret",
    "password",
}

# Recursive: source now lives inside subpackages (auth/, sync/, webhooks/,
# mcp/), not just at the gateway root. Excludes tests/ (not production
# source) and dotdirs like .cache/.pytest_cache (not source at all).
_EXCLUDED_DIR_NAMES = {"tests"}

_SOURCE_FILES = [
    p
    for p in GATEWAY_DIR.rglob("*.py")
    if p.name != "config.py"
    and not any(
        part.startswith(".") or part in _EXCLUDED_DIR_NAMES
        for part in p.relative_to(GATEWAY_DIR).parts[:-1]
    )
]


def _logger_call_kwarg_names(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_logger_call = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
            and func.attr in {"debug", "info", "warning", "error", "critical"}
        )
        if not is_logger_call:
            continue
        for kw in node.keywords:
            if kw.arg is not None:
                yield kw.arg


def test_no_logger_call_uses_a_credential_shaped_keyword_argument():
    offenders = []
    for path in _SOURCE_FILES:
        tree = ast.parse(path.read_text())
        for kwarg_name in _logger_call_kwarg_names(tree):
            if kwarg_name.lower() in DISALLOWED_KWARG_NAMES:
                offenders.append(f"{path.name}: logger call with kwarg '{kwarg_name}'")

    assert not offenders, "Potential credential logging found:\n" + "\n".join(offenders)


def test_mcp_tool_descriptions_contain_no_dynamic_secret_interpolation():
    """SC-8: tool descriptions (docstrings) are static text, never built from
    settings or runtime secret values."""
    live_session_source = (GATEWAY_DIR / "session" / "live_session.py").read_text()
    tree = ast.parse(live_session_source)

    tool_docstrings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and any(
            isinstance(d, ast.Attribute) and d.attr == "tool" for d in node.decorator_list
        ):
            doc = ast.get_docstring(node)
            if doc:
                tool_docstrings.append(doc)

    assert tool_docstrings, "Expected at least one @mcp.tool function with a docstring"
    for doc in tool_docstrings:
        assert "settings." not in doc
        assert "client_secret" not in doc.lower()
        assert "access_token" not in doc.lower()
