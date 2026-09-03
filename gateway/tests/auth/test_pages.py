"""Unit tests for the human-readable install outcome pages
(auth/pages.py), specifically that every interpolated value is HTML-escaped
— title/message/hub_id can carry HubSpot-sourced text (an OAuth error
field, a token-exchange response value), and the URL is derived from the
incoming request's own Host header, neither of which this project
controls."""

from types import SimpleNamespace

from auth.pages import error_page, install_success_page


def _fake_request(host: str = "http://localhost:8888") -> SimpleNamespace:
    return SimpleNamespace(base_url=host)


def test_install_success_page_escapes_hub_id():
    response = install_success_page(
        "Setup Complete", '148997330"><script>alert(1)</script>', "All good."
    )
    body = response.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_install_success_page_escapes_message():
    response = install_success_page(
        "Setup Complete", "148997330", '<img src=x onerror="alert(1)">'
    )
    body = response.body.decode()
    assert '<img src=x onerror="alert(1)">' not in body
    assert "&lt;img" in body


def test_install_success_page_escapes_next_url_host():
    request = _fake_request('http://"><script>evil</script>.example.com')
    response = install_success_page(
        "Connected", "148997330", "Done.", request=request,
        next_path="/next-step", next_label="Continue",
    )
    body = response.body.decode()
    assert "<script>evil</script>" not in body


def test_error_page_escapes_hubspot_error_field():
    response = error_page(
        "Connection Failed",
        'HubSpot reported an error: "><script>alert(1)</script>',
        400,
    )
    body = response.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_error_page_escapes_retry_url_host():
    request = _fake_request('http://"><script>evil</script>.example.com')
    response = error_page(
        "Connection Failed", "Try again.", 400,
        request=request, retry_path="/install",
    )
    body = response.body.decode()
    assert "<script>evil</script>" not in body
