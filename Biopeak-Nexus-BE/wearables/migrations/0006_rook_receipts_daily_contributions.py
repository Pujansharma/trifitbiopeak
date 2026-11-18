# Stage 1 of removing RookHealthDocument and HealthObservation.
#
# 1. Add the canonical-document fields to RookWebhookReceipt and the per-document
#    contributions to HealthDailySummary.
# 2. Backfill them from the existing rows, so no accepted data is lost:
#    - every receipt linked to a document inherits its identity, version and hash;
#    - queued documents keep their raw body on the receipt so the worker can finish them;
#    - each current observation is folded into the summary for its day/metric/source.
# Stage 2 (0007) drops the foreign keys and the two tables. The split keeps the
# data updates and the ALTER TABLE statements in separate transactions, which
# avoids PostgreSQL "pending trigger events" errors on deferred foreign keys.

import hashlib
import json
from datetime import UTC, datetime

from django.db import migrations, models

QUEUED = "queued"
RECEIVED = "received"
PROCESSED = "processed"
REJECTED = "rejected"


def _digest(value):
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _at(entry):
    return datetime.fromisoformat(entry["at"]).astimezone(UTC)


def _summarize(contributions):
    """Same aggregate rules as wearables/services/daily_contributions.summarize."""
    entries = list(contributions.values())
    numeric = [entry for entry in entries if entry.get("n")]
    count = sum(entry["n"] for entry in numeric)
    total = sum(entry["s"] for entry in numeric) if numeric else None
    latest_numeric = max(numeric, key=_at) if numeric else None
    last_entry = max(entries, key=_at)
    first_entry = min(entries, key=_at)
    return {
        "count": count,
        "minimum": min((entry["mn"] for entry in numeric), default=None),
        "maximum": max((entry["mx"] for entry in numeric), default=None),
        "average": total / count if count else None,
        "total": total,
        "latest": latest_numeric["lv"] if latest_numeric else None,
        "unit": last_entry.get("u", ""),
        "completeness": 1.0,
        "first_observed_at": _at(first_entry),
        "last_observed_at": _at(last_entry),
        "data_sources": sorted({source for entry in entries for source in entry.get("ds", [])}),
    }


def _version(payload, fallback):
    try:
        value = int((payload or {}).get("document_version") or fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(1, value)


def _accumulate(contributions, row):
    (identity, version, unit, observed_at, number, text, boolean,
     confidence, data_sources, provenance) = row
    entry = contributions.get(identity)
    if entry is None:
        entry = {
            "v": version, "u": unit, "n": 0, "s": 0.0,
            "at": observed_at.astimezone(UTC).isoformat(),
            "ds": list(data_sources or []), "cf": 1.0,
        }
        contributions[identity] = entry
    entry["v"] = max(entry["v"], version)
    if number is not None:
        value = float(number)
        entry["n"] += 1
        entry["s"] += value
        entry["mn"] = min(entry.get("mn", value), value)
        entry["mx"] = max(entry.get("mx", value), value)
        entry["lv"] = value
    elif boolean is not None:
        entry["tv"] = bool(boolean)
    elif text:
        entry["tv"] = str(text)[:512]
    if confidence is not None:
        entry["cf"] = min(entry["cf"], float(confidence))
    if isinstance(provenance, dict):
        if provenance.get("sourceChange"):
            entry["sc"] = provenance["sourceChange"]
        if provenance.get("clinicalReviewSuggested"):
            entry["cr"] = True


def backfill(apps, schema_editor):
    Document = apps.get_model("wearables", "RookHealthDocument")
    Receipt = apps.get_model("wearables", "RookWebhookReceipt")
    Observation = apps.get_model("wearables", "HealthObservation")
    Summary = apps.get_model("wearables", "HealthDailySummary")

    # A. Receipts: inherit canonical identity; keep queued bodies.
    for document in Document.objects.select_related("identity").iterator():
        linked = list(Receipt.objects.filter(document_id=document.pk).order_by("received_at", "pk"))
        current_version_queued = [
            receipt for receipt in linked
            if receipt.status == QUEUED and _version(receipt.payload, document.document_version) == document.document_version
        ]
        body_owner = current_version_queued[-1].pk if current_version_queued else None
        has_lineage = False
        for receipt in linked:
            version = _version(receipt.payload, document.document_version)
            receipt.document_identity = document.document_identity
            receipt.document_version = version
            receipt.observed_at = document.observed_at
            if version == document.document_version and receipt.status in (QUEUED, PROCESSED, RECEIVED):
                receipt.content_hash = document.content_hash
            if document.status == PROCESSED and receipt.status in (QUEUED, RECEIVED):
                receipt.status = PROCESSED
                receipt.payload = {}
            elif receipt.status in (QUEUED, RECEIVED):
                if receipt.pk == body_owner and document.payload:
                    receipt.status = QUEUED
                    receipt.payload = document.payload
                else:
                    receipt.status = REJECTED
                    receipt.reason = "lower_document_version"
                    receipt.payload = {}
            receipt.save(update_fields=[
                "document_identity", "document_version", "content_hash", "observed_at",
                "status", "reason", "payload",
            ])
            if version == document.document_version and receipt.status in (QUEUED, PROCESSED):
                has_lineage = True
        if not has_lineage:
            # Documents with no receipt for their current version still need lineage,
            # so later corrections are compared against them.
            if document.status == PROCESSED:
                status, payload = PROCESSED, {}
            elif document.status in (QUEUED, RECEIVED) and document.payload:
                status, payload = QUEUED, document.payload
            else:
                status, payload = REJECTED, {}
            Receipt.objects.get_or_create(
                receipt_key=_digest(["migrated", str(document.pk)]),
                defaults={
                    "rook_user_id": document.identity.rook_user_id,
                    "document_identity": document.document_identity,
                    "document_version": document.document_version,
                    "content_hash": document.content_hash,
                    "observed_at": document.observed_at,
                    "signature_valid": False,
                    "status": status,
                    "reason": "migrated_from_document"[:128],
                    "payload": payload,
                    "received_at": document.received_at,
                },
            )

    # B. Summaries: rebuild every row from current observations (the source of truth
    #    for the old aggregates), replacing any stale rows.
    Summary.objects.all().delete()
    observations = (
        Observation.objects.filter(is_current=True)
        .order_by("customer_profile_id", "local_date", "domain", "metric", "source_key")
        .values_list(
            "customer_profile_id", "local_date", "domain", "metric", "source_key",
            "unit", "document__document_identity", "document_version", "observed_at",
            "numeric_value", "text_value", "boolean_value", "confidence",
            "data_sources", "provenance",
        )
    )
    group_key, contributions, batch = None, {}, []
    for row in observations.iterator(chunk_size=2000):
        key = row[:5]
        if key != group_key:
            if group_key is not None:
                batch.append(_summary_row(Summary, group_key, contributions))
                if len(batch) >= 500:
                    Summary.objects.bulk_create(batch)
                    batch = []
            group_key, contributions = key, {}
        _accumulate(contributions, (row[6], row[7], row[5], row[8], row[9], row[10], row[11], row[12], row[13], row[14]))
    if group_key is not None:
        batch.append(_summary_row(Summary, group_key, contributions))
    if batch:
        Summary.objects.bulk_create(batch)


def _summary_row(Summary, key, contributions):
    profile_id, local_date, domain, metric, source_key = key
    return Summary(
        customer_profile_id=profile_id,
        domain=domain,
        metric=metric,
        local_date=local_date,
        source_key=source_key,
        contributions=contributions,
        **_summarize(contributions),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("wearables", "0005_rookoutbox_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rookwebhookreceipt",
            name="document_identity",
            field=models.CharField(max_length=64, blank=True),
        ),
        migrations.AddField(
            model_name="rookwebhookreceipt",
            name="document_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="rookwebhookreceipt",
            name="content_hash",
            field=models.CharField(max_length=64, blank=True),
        ),
        migrations.AddField(
            model_name="rookwebhookreceipt",
            name="observed_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="rookwebhookreceipt",
            index=models.Index(fields=["document_identity", "status"], name="w_rookwebhook_ident_idx"),
        ),
        migrations.AddField(
            model_name="healthdailysummary",
            name="contributions",
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.AddField(
            model_name="healthdailysummary",
            name="data_sources",
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
