"""Sybill webhook receiver: Svix-style signature validation, tenant
resolution, transcript normalization, and Airtable staging.

Sybill signs webhooks via Svix (confirmed against Sybill's own published
docs, help.sybill.ai/en/articles/9925117). Verification is implemented
directly against Svix's documented scheme rather than the `svix` SDK, to
avoid adding an unverified new dependency; the algorithm itself is public
and stable (svix-id, svix-timestamp, svix-signature headers, HMAC-SHA256).

Open item, flagged not guessed: Sybill's payload carries no hub_id of its
own. Tenant is resolved via crmInfo.accountId/opportunityId against the
hubspot_object_index (populated by sync.airtable_staging as Companies/Deals are
staged). If that lookup is ambiguous or empty, the payload is rejected
rather than guessed at, since a wrong guess here would be a cross-tenant
leak. This needs validating against real traffic before go-live.
"""

import base64
import hashlib
import hmac
import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from pyairtable import Api

from auth import record_audit
from config import settings
from db import get_pool
from sync import SYBILL_TABLE, normalize_sybill_transcript

logger = structlog.get_logger()

router = APIRouter()

_REPLAY_WINDOW_SECONDS = 5 * 60


class SybillTenantResolutionError(Exception):
    """Raised when the tenant for a payload can't be resolved unambiguously."""


def verify_svix_signature(
    body: bytes, svix_id: str, svix_timestamp: str, svix_signature: str, secret: str
) -> bool:
    """Verifies a Svix-signed webhook per Svix's documented scheme.

    secret may be given with or without the "whsec_" prefix Svix normally
    uses; both forms are handled.
    """
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    try:
        if abs(time.time() - int(svix_timestamp)) > _REPLAY_WINDOW_SECONDS:
            return False
    except ValueError:
        return False

    raw_secret = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    try:
        secret_bytes = base64.b64decode(raw_secret)
    except Exception:
        secret_bytes = raw_secret.encode("utf-8")

    signed_content = f"{svix_id}.{svix_timestamp}.".encode("utf-8") + body
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("ascii")

    for candidate in svix_signature.split():
        candidate_sig = candidate.split(",", 1)[-1]
        if hmac.compare_digest(candidate_sig, expected):
            return True
    return False


async def resolve_hub_id(payload: dict) -> str:
    """Resolves the owning tenant from crmInfo, or raises if ambiguous/unknown."""
    crm_info = payload.get("data", {}).get("crmInfo", {}) or {}
    candidate_ids = [
        ("company", crm_info.get("accountId")),
        ("deal", crm_info.get("opportunityId")),
    ]

    pool = await get_pool()
    matched_hub_ids: set[str] = set()
    for object_type, object_id in candidate_ids:
        if not object_id:
            continue
        rows = await pool.fetch(
            "SELECT DISTINCT hub_id FROM hubspot_object_index WHERE object_type = $1 AND object_id = $2",
            object_type,
            str(object_id),
        )
        matched_hub_ids.update(row["hub_id"] for row in rows)

    if len(matched_hub_ids) != 1:
        raise SybillTenantResolutionError(
            f"Could not uniquely resolve tenant (matches={len(matched_hub_ids)})"
        )
    return next(iter(matched_hub_ids))


@router.post("/webhooks/sybill")
async def sybill_webhook(request: Request) -> dict:
    body = await request.body()
    svix_id = request.headers.get("svix-id", "")
    svix_timestamp = request.headers.get("svix-timestamp", "")
    svix_signature = request.headers.get("svix-signature", "")

    if not verify_svix_signature(body, svix_id, svix_timestamp, svix_signature, settings.sybill_webhook):
        logger.warning("sybill_webhook.invalid_signature")
        raise HTTPException(401, "Invalid or stale signature")

    payload = await request.json()

    try:
        hub_id = await resolve_hub_id(payload)
    except SybillTenantResolutionError as exc:
        logger.error("sybill_webhook.tenant_resolution_failed", error=str(exc))
        raise HTTPException(422, "Could not resolve owning tenant for this payload") from exc

    record = normalize_sybill_transcript(hub_id, payload)
    record.pop("_meeting_title", None)

    api = Api(settings.airtable_api_key)
    table = api.base(settings.airtable_base_id).table(SYBILL_TABLE)
    table.create(record)

    await record_audit(
        "sybill_transcript_staged", hub_id=hub_id, detail={"event_id": payload.get("eventId")}
    )
    logger.info("sybill_webhook.staged", hub_id=hub_id, event_id=payload.get("eventId"))
    return {"status": "staged", "hub_id": hub_id}
