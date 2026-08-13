"""Task 5.6: proves a forged or stale payload is rejected, and exercises
tenant resolution via the hubspot_object_index."""

import base64
import hashlib
import hmac
import time

import pytest

from config import settings
from db import get_pool
from webhooks.sybill import SybillTenantResolutionError, resolve_hub_id, verify_svix_signature


def _sign(body: bytes, svix_id: str, timestamp: str, secret: str) -> str:
    raw_secret = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    secret_bytes = base64.b64decode(raw_secret)
    signed_content = f"{svix_id}.{timestamp}.".encode() + body
    sig = base64.b64encode(hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()).decode()
    return f"v1,{sig}"


def test_valid_signature_accepted():
    body = b'{"eventType": "meeting.new_recording.v1"}'
    svix_id = "msg_1"
    timestamp = str(int(time.time()))
    signature = _sign(body, svix_id, timestamp, settings.sybill_webhook)

    assert verify_svix_signature(body, svix_id, timestamp, signature, settings.sybill_webhook) is True


def test_tampered_body_rejected():
    body = b'{"eventType": "meeting.new_recording.v1"}'
    svix_id = "msg_1"
    timestamp = str(int(time.time()))
    signature = _sign(body, svix_id, timestamp, settings.sybill_webhook)

    tampered_body = b'{"eventType": "meeting.deleted.v1"}'
    assert verify_svix_signature(tampered_body, svix_id, timestamp, signature, settings.sybill_webhook) is False


def test_wrong_secret_rejected():
    body = b'{"eventType": "meeting.new_recording.v1"}'
    svix_id = "msg_1"
    timestamp = str(int(time.time()))
    signature = _sign(body, svix_id, timestamp, "whsec_" + base64.b64encode(b"wrong-secret-32-bytes-long-000").decode())

    assert verify_svix_signature(body, svix_id, timestamp, signature, settings.sybill_webhook) is False


def test_stale_timestamp_rejected():
    body = b'{"eventType": "meeting.new_recording.v1"}'
    svix_id = "msg_1"
    stale_timestamp = str(int(time.time()) - 600)  # 10 minutes old
    signature = _sign(body, svix_id, stale_timestamp, settings.sybill_webhook)

    assert verify_svix_signature(body, svix_id, stale_timestamp, signature, settings.sybill_webhook) is False


def test_missing_signature_rejected():
    body = b'{"eventType": "meeting.new_recording.v1"}'
    assert verify_svix_signature(body, "", "", "", settings.sybill_webhook) is False


@pytest.mark.asyncio
async def test_resolve_hub_id_unique_match():
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO hubspot_object_index (object_type, object_id, hub_id) VALUES ('company', 'acc-1', 'hub_a')"
    )
    payload = {"data": {"crmInfo": {"accountId": "acc-1"}}}
    assert await resolve_hub_id(payload) == "hub_a"


@pytest.mark.asyncio
async def test_resolve_hub_id_no_match_raises():
    payload = {"data": {"crmInfo": {"accountId": "unknown-id"}}}
    with pytest.raises(SybillTenantResolutionError):
        await resolve_hub_id(payload)


@pytest.mark.asyncio
async def test_resolve_hub_id_ambiguous_match_raises():
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO hubspot_object_index (object_type, object_id, hub_id) VALUES ('company', 'acc-shared', 'hub_a')"
    )
    await pool.execute(
        "INSERT INTO hubspot_object_index (object_type, object_id, hub_id) VALUES ('company', 'acc-shared', 'hub_b')"
    )
    payload = {"data": {"crmInfo": {"accountId": "acc-shared"}}}
    with pytest.raises(SybillTenantResolutionError):
        await resolve_hub_id(payload)
