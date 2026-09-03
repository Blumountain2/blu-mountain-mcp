"""Minimal, dependency-free HTML pages shown in a portal admin's browser at
the end of an OAuth install redirect. These are the only two human-facing
pages in this service — a full templating engine isn't warranted for that,
so this is a plain function returning an inline HTML string."""

import html

from fastapi import Request
from fastapi.responses import HTMLResponse

_STYLE = """
    * { box-sizing: border-box; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        margin: 0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #f5f3ff 0%, #eef2ff 100%);
        color: #1a1a2e;
    }
    .card {
        background: #fff;
        max-width: 28rem;
        width: 100%;
        margin: 1.5rem;
        padding: 2.5rem 2rem;
        border-radius: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 12px 32px rgba(30,20,80,0.08);
        text-align: center;
    }
    .icon {
        width: 3rem;
        height: 3rem;
        margin: 0 auto 1.25rem;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .icon.success { background: #ecfdf5; }
    .icon.error { background: #fef2f2; }
    h1 {
        font-size: 1.35rem;
        margin: 0 0 0.6rem;
        letter-spacing: -0.01em;
    }
    p.message {
        color: #4b5563;
        line-height: 1.55;
        margin: 0 0 1.25rem;
    }
    .portal-id {
        display: inline-block;
        color: #6b7280;
        font-size: 0.8rem;
        background: #f3f4f6;
        padding: 0.25rem 0.65rem;
        border-radius: 999px;
        margin-bottom: 1.5rem;
    }
    .next-step {
        border-top: 1px solid #eef0f3;
        padding-top: 1.5rem;
        margin-top: 0.5rem;
    }
    .next-label {
        font-size: 0.8rem;
        color: #6b7280;
        margin-bottom: 0.5rem;
    }
    a.url-link {
        display: block;
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
        font-size: 0.82rem;
        color: #4f46e5;
        background: #f5f5fb;
        border: 1px solid #e5e3f5;
        border-radius: 8px;
        padding: 0.6rem 0.75rem;
        margin-bottom: 0.9rem;
        text-decoration: none;
        word-break: break-all;
        transition: background 0.15s ease;
    }
    a.url-link:hover { background: #ececfa; }
    a.button {
        display: inline-block;
        padding: 0.65rem 1.6rem;
        background: #ff7a59;
        color: #fff;
        font-weight: 600;
        font-size: 0.92rem;
        text-decoration: none;
        border-radius: 8px;
        transition: background 0.15s ease;
    }
    a.button:hover { background: #ff6440; }
    .close-note {
        color: #9ca3af;
        font-size: 0.85rem;
        margin-top: 0.25rem;
    }
"""

_CHECK_ICON = (
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" '
    'stroke="#059669" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20 6 9 17l-5-5"/></svg>'
)

_ERROR_ICON = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'stroke="#dc2626" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>'
)


def _render_page(title: str, icon_class: str, icon_svg: str, body_html: str, status_code: int = 200) -> HTMLResponse:
    """Shared outer HTML shell for both page functions below — the entire
    <!doctype html>...</html> structure was previously duplicated
    verbatim in each, differing only in the icon and the card's body
    content. `title` is escaped here since both callers pass it through
    unescaped."""
    page = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{html.escape(title)}</title><style>{_STYLE}</style></head>
<body>
<div class="card">
<div class="icon {icon_class}">{icon_svg}</div>
<h1>{html.escape(title)}</h1>
{body_html}
</div>
</body>
</html>"""
    return HTMLResponse(page, status_code=status_code)


def install_success_page(
    title: str,
    hub_id: str,
    message: str,
    request: Request | None = None,
    next_path: str | None = None,
    next_label: str = "",
) -> HTMLResponse:
    """Renders a success page for a completed install step. If next_path is
    given, shows that step's full absolute URL as a clickable link (derived
    from the incoming request's own host, so it's correct in any
    environment) alongside a Continue button, instead of a
    close-this-window note. Every value interpolated into the returned HTML
    is escaped — title/message/hub_id can carry HubSpot-sourced text (e.g.
    an OAuth error field), and the URL is derived from the incoming
    request's own Host header, neither of which this project controls."""
    if next_path:
        next_url = str(request.base_url).rstrip("/") + next_path if request else next_path
        next_url_escaped = html.escape(next_url)
        next_html = f"""<div class="next-step">
    <div class="next-label">Next step</div>
    <a class="url-link" href="{next_url_escaped}">{next_url_escaped}</a>
    <a class="button" href="{next_url_escaped}">{html.escape(next_label)}</a>
</div>"""
    else:
        next_html = '<p class="close-note">You can close this window.</p>'

    body_html = (
        f'<p class="message">{html.escape(message)}</p>'
        f'<div class="portal-id">Portal ID: {html.escape(hub_id)}</div>'
        f"{next_html}"
    )
    return _render_page(title, "success", _CHECK_ICON, body_html)


def error_page(
    title: str,
    message: str,
    status_code: int,
    request: Request | None = None,
    retry_path: str | None = None,
    retry_label: str = "Start over",
) -> HTMLResponse:
    """Renders an error page for a failed install step — same visual
    design as install_success_page (a red icon instead of green, no portal
    ID since a failed step often has none yet), with an optional retry
    link back to the step that failed. Every value interpolated into the
    returned HTML is escaped — message can carry HubSpot-sourced text
    (e.g. an OAuth error field), and the URL is derived from the incoming
    request's own Host header, neither of which this project controls."""
    if retry_path:
        retry_url = str(request.base_url).rstrip("/") + retry_path if request else retry_path
        retry_url_escaped = html.escape(retry_url)
        retry_html = f"""<div class="next-step">
    <a class="url-link" href="{retry_url_escaped}">{retry_url_escaped}</a>
    <a class="button" href="{retry_url_escaped}">{html.escape(retry_label)}</a>
</div>"""
    else:
        retry_html = '<p class="close-note">Close this window and try again.</p>'

    body_html = f'<p class="message">{html.escape(message)}</p>{retry_html}'
    return _render_page(title, "error", _ERROR_ICON, body_html, status_code=status_code)
