import re
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Case, Exists, F, OuterRef, When
from django.utils import timezone
from requests import ConnectionError, Response, Session, Timeout
from requests.exceptions import JSONDecodeError, RequestException

from accounts.customers.models import CustomerProfile
from accounts.users.models import User
from core.utils.exceptions import bad_request
from core.utils.log import logger
from leads.models import Lead
from supplementation.models import (
    AiRecommendation,
    AiRecommendationItem,
    ClientConstraint,
    Protocol,
    ProtocolAiJob,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
    Supplement,
)
from supplementation.utils.constants import (
    OPEN_AI_RECOMMENDATION_DECISIONS,
    AiRecommendationItemDecision,
    AiRecommendationItemOrigin,
    AiRecommendationStatus,
    ProtocolAiJobStatus,
    ProtocolEventAction,
    ProtocolItemFrequency,
    ProtocolItemTiming,
    ProtocolVersionStatus,
)

MAX_PROTOCOL_AI_ATTEMPTS = 2
STALE_PROTOCOL_AI_PROCESSING = timedelta(minutes=2)
LUMA_NEXUS_CLIENTS_PATH = "/luma/v1/integrations/nexus/clients"
LUMA_UNAVAILABLE = "Luma is unavailable."
LUMA_ERROR_MESSAGES = {
    401: "Luma rejected the Nexus API key.",
    404: "Luma could not find this client.",
    409: "Luma could not confirm this client's identity.",
    422: "Luma could not build a recommendation for this client.",
}
UUID_TEXT_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ITEM_ALREADY_DECIDED = "This item is already accepted or rejected."
DRAFT_ALREADY_CREATED = "A draft was already created from this recommendation."
DRAFT_UNDECIDED = "Accept or reject every supplement before creating the draft."
DRAFT_NONE_ACCEPTED = "Accept at least one supplement before creating the draft."
DRAFT_MISSING_DOSE = "An accepted supplement is missing a dose."
INACTIVE_SUPPLEMENT_DETAIL = "Supplement is inactive."
RECOMMENDATION_SAVE_FAILED = "Could not save the recommendation."
EXPECTED_ITEM_ORIGIN = {
    True: AiRecommendationItemOrigin.REQUESTED,
    False: AiRecommendationItemOrigin.AI_ADDED,
}


class ProtocolRecommendationError(Exception):
    pass


def supplement_request_payload(supplement: Supplement) -> dict:
    return {
        "id": str(supplement.pk),
        "product_name": supplement.product_name,
        "brand_name": supplement.brand.name,
        "form": supplement.form,
        "serving_size": supplement.serving_size,
        "active_ingredients": [
            {
                "ingredient_name": ingredient.ingredient_name,
                "serving": str(ingredient.serving),
                "unit": ingredient.unit,
            }
            for ingredient in supplement.active_ingredients.all()
        ],
        "allergen_information": [
            {"name": allergen.name, "type": allergen.presence_type}
            for allergen in supplement.allergens.all()
        ],
    }


def constraint_request_payload(constraint: ClientConstraint) -> dict:
    return {
        "kind": constraint.kind,
        "name": constraint.name,
        "severity": constraint.severity,
        "notes": constraint.notes,
    }


def ordered_active_supplements(supplement_ids: list[UUID]) -> list[Supplement]:
    supplements = (
        Supplement.objects.select_related("brand")
        .prefetch_related(
            "active_ingredients",
            "allergens",
        )
        .filter(pk__in=supplement_ids, is_active=True)
    )
    supplements_by_id = {supplement.pk: supplement for supplement in supplements}
    ordered = [
        supplements_by_id[supplement_id]
        for supplement_id in supplement_ids
        if supplement_id in supplements_by_id
    ]
    if len(ordered) != len(supplement_ids):
        raise ProtocolRecommendationError("A requested supplement is no longer active.")
    return ordered


# ponytail: copy of get_metsights_profile_id in
# integrations/intelligence_engine/luma/supplementation.py (PR #113); import it from
# there once both branches are merged.
def get_metsights_profile_id(customer_profile: CustomerProfile) -> str | None:
    """
    Customer create stores the Metsights id on profile.data, lead create/update on
    lead.data (MetsightsProfile is not written). Both run for the main profile only,
    and Metsights is looked up by phone, so a family profile gets no hint.
    """
    if not customer_profile.is_main:
        return None
    profile_id = (customer_profile.data or {}).get("metsights_profile_id")
    if profile_id:
        return profile_id
    lead_data = (
        Lead.objects.filter(customer_profile=customer_profile)
        .values_list("data", flat=True)
        .first()
    )
    return (lead_data or {}).get("metsights_profile_id")


def recommendation_request_body(job: ProtocolAiJob) -> dict:
    supplements = ordered_active_supplements(job.supplement_ids)
    constraints = ClientConstraint.objects.filter(
        customer_profile=job.customer_profile,
        is_active=True,
    ).order_by("name", "created_at")
    return {
        "customer_profile_id": str(job.customer_profile_id),
        "metsights_profile_id": get_metsights_profile_id(job.customer_profile),
        "name": job.name,
        "purpose": job.purpose,
        "notes": job.notes,
        "supplements": [
            supplement_request_payload(supplement) for supplement in supplements
        ],
        "constraints": [
            constraint_request_payload(constraint) for constraint in constraints
        ],
    }


def recommendation_response_data(response: Response) -> dict:
    response_context = (
        f"endpoint={response.url} status={response.status_code} "
        f"content_type={response.headers.get('Content-Type', '')} "
        f"elapsed_seconds={response.elapsed.total_seconds()}"
    )
    if not response.ok:
        logger.error(
            f"Luma request failed: {response_context} reason=upstream_http_error"
        )
        # ponytail: 401/404/409/422 still burn both attempts; add a terminal job
        # state if that retry ever costs anything.
        raise ProtocolRecommendationError(
            LUMA_ERROR_MESSAGES.get(response.status_code, LUMA_UNAVAILABLE)
        )
    try:
        payload = response.json()
    except JSONDecodeError:
        logger.error(f"Luma request failed: {response_context} reason=invalid_json")
        raise ProtocolRecommendationError(
            "Luma returned an invalid response."
        ) from None
    if not isinstance(payload, dict):
        logger.error(
            f"Luma request failed: {response_context} reason=expected_json_object"
        )
        raise ProtocolRecommendationError("Luma returned an invalid response.")
    return payload


def post_protocol_recommendation(body: dict) -> dict:
    path = (
        f"{LUMA_NEXUS_CLIENTS_PATH}/{body['customer_profile_id']}"
        "/protocol-recommendation"
    )
    logging_context = f"operation=protocol_recommend endpoint={path}"
    luma_base_url = str(settings.LUMA_BASE_URL or "").strip()
    luma_nexus_api_key = str(settings.LUMA_NEXUS_API_KEY or "").strip()
    if not luma_base_url or not luma_nexus_api_key:
        logger.error(f"Luma request failed: {logging_context} reason=not_configured")
        raise ProtocolRecommendationError("Luma is not configured.")
    logger.info(f"Luma request started: {logging_context}")
    session = Session()
    session.headers.update({"X-API-Key": luma_nexus_api_key})
    try:
        response = session.post(
            f"{luma_base_url.rstrip('/')}{path}",
            json=body,
            timeout=60,
        )
    except (ConnectionError, Timeout) as error:
        logger.error(
            f"Luma request failed: {logging_context} "
            f"reason=connection_or_timeout error_type={type(error).__name__}",
            exc_info=True,
        )
        raise ProtocolRecommendationError("Luma is unavailable.") from None
    finally:
        session.close()
    return recommendation_response_data(response)


def required_recommendation_text(payload: dict, key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolRecommendationError(f"Luma returned an invalid {label}.")
    return value.strip()


def parsed_supplement_id(value: object) -> UUID:
    if not isinstance(value, str) or UUID_TEXT_PATTERN.fullmatch(value) is None:
        raise ProtocolRecommendationError("Luma returned an invalid supplement.")
    return UUID(value)


def parsed_custom_frequency(
    frequency: str,
    custom_frequency: object,
) -> str | None:
    if isinstance(custom_frequency, str):
        custom_frequency = custom_frequency.strip() or None
    if custom_frequency is not None and not isinstance(custom_frequency, str):
        raise ProtocolRecommendationError(
            "Luma returned an invalid custom frequency."
        )
    if frequency == ProtocolItemFrequency.CUSTOM:
        if custom_frequency is None:
            raise ProtocolRecommendationError(
                "Luma returned an invalid custom frequency."
            )
        return custom_frequency
    if custom_frequency is not None:
        raise ProtocolRecommendationError(
            "Luma returned an invalid custom frequency."
        )
    return None


def parsed_recommendation_item(raw_item: object) -> dict:
    if not isinstance(raw_item, dict):
        raise ProtocolRecommendationError("Luma returned an invalid supplement.")
    frequency = raw_item.get("frequency")
    timing = raw_item.get("timing")
    if frequency not in ProtocolItemFrequency.values:
        raise ProtocolRecommendationError("Luma returned an invalid frequency.")
    if timing not in ProtocolItemTiming.values:
        raise ProtocolRecommendationError("Luma returned an invalid timing.")
    return {
        "supplement_id": parsed_supplement_id(raw_item.get("supplement_id")),
        "origin": raw_item.get("origin"),
        "dosage": required_recommendation_text(raw_item, "dosage", "dosage"),
        "frequency": frequency,
        "custom_frequency": parsed_custom_frequency(
            frequency,
            raw_item.get("custom_frequency"),
        ),
        "timing": timing,
        "duration": required_recommendation_text(raw_item, "duration", "duration"),
        "instructions": required_recommendation_text(
            raw_item,
            "instructions",
            "instructions",
        ),
        "rationale": required_recommendation_text(raw_item, "rationale", "rationale"),
    }


def active_extra_supplement_ids(extra_ids: set[UUID]) -> set[UUID]:
    if not extra_ids:
        return set()
    return set(
        Supplement.objects.filter(pk__in=extra_ids, is_active=True).values_list(
            "pk",
            flat=True,
        )
    )


def parse_protocol_recommendation(payload: dict, requested_ids: set[UUID]) -> dict:
    model_name = payload.get("model")
    model_name_invalid = (
        not isinstance(model_name, str)
        or not model_name.strip()
        or len(model_name) > 128
    )
    if model_name_invalid:
        raise ProtocolRecommendationError("Luma returned no model.")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ProtocolRecommendationError("Luma returned no supplements.")
    items = [parsed_recommendation_item(raw_item) for raw_item in raw_items]
    returned_ids = [item["supplement_id"] for item in items]
    if len(returned_ids) != len(set(returned_ids)):
        raise ProtocolRecommendationError("Luma returned a duplicate supplement.")
    if requested_ids - set(returned_ids):
        raise ProtocolRecommendationError("Luma omitted a requested supplement.")
    extra_ids = set(returned_ids) - requested_ids
    if active_extra_supplement_ids(extra_ids) != extra_ids:
        raise ProtocolRecommendationError("Luma returned an unknown supplement.")
    for item in items:
        expected_origin = EXPECTED_ITEM_ORIGIN[item["supplement_id"] in requested_ids]
        if item["origin"] not in (None, expected_origin):
            raise ProtocolRecommendationError("Luma returned an invalid origin.")
        item["origin"] = expected_origin
    return {"model": model_name.strip(), "items": items}


def request_protocol_recommendation(job: ProtocolAiJob) -> dict:
    payload = post_protocol_recommendation(recommendation_request_body(job))
    return parse_protocol_recommendation(payload, set(job.supplement_ids))


def recommendation_items(
    recommendation: AiRecommendation,
    parsed_items: list[dict],
) -> list[AiRecommendationItem]:
    return [
        AiRecommendationItem(
            recommendation=recommendation,
            supplement_id=item["supplement_id"],
            origin=item["origin"],
            decision=AiRecommendationItemDecision.PENDING,
            dosage=item["dosage"],
            frequency=item["frequency"],
            custom_frequency=item["custom_frequency"],
            timing=item["timing"],
            duration=item["duration"],
            instructions=item["instructions"],
            rationale=item["rationale"],
        )
        for item in parsed_items
    ]


def save_protocol_recommendation(
    job: ProtocolAiJob,
    result: dict,
) -> AiRecommendation | None:
    try:
        with transaction.atomic():
            recommendation = AiRecommendation.objects.create(
                job=job,
                customer_profile=job.customer_profile,
                name=job.name,
                purpose=job.purpose,
                notes=job.notes,
                model=result["model"],
                status=AiRecommendationStatus.UNDER_REVIEW,
            )
            AiRecommendationItem.objects.bulk_create(
                recommendation_items(recommendation, result["items"])
            )
            saved = ProtocolAiJob.objects.filter(
                pk=job.pk,
                status=ProtocolAiJobStatus.PROCESSING,
            ).update(
                status=ProtocolAiJobStatus.COMPLETED,
                error_detail="",
                updated_at=timezone.localtime(),
            )
            if saved == 0:
                transaction.set_rollback(True)
                return None
            return recommendation
    except IntegrityError:
        existing = AiRecommendation.objects.filter(job=job).first()
        if existing is None:
            raise
        return existing


def fail_protocol_ai_job(job_id: UUID, detail: str) -> None:
    ProtocolAiJob.objects.filter(
        pk=job_id,
        status=ProtocolAiJobStatus.PROCESSING,
    ).update(
        status=ProtocolAiJobStatus.FAILED,
        error_detail=detail[:2000],
        updated_at=timezone.localtime(),
    )


def claim_protocol_ai_job(job_id: UUID) -> ProtocolAiJob | None:
    updated = ProtocolAiJob.objects.filter(
        pk=job_id,
        status__in=[ProtocolAiJobStatus.PENDING, ProtocolAiJobStatus.FAILED],
        attempt_count__lt=MAX_PROTOCOL_AI_ATTEMPTS,
    ).update(
        status=ProtocolAiJobStatus.PROCESSING,
        attempt_count=F("attempt_count") + 1,
        error_detail="",
        updated_at=timezone.localtime(),
    )
    if updated != 1:
        return None
    return (
        ProtocolAiJob.objects.select_related("customer_profile")
        .filter(pk=job_id)
        .first()
    )


def process_protocol_ai_job(job_id: UUID) -> UUID | None:
    job = claim_protocol_ai_job(job_id)
    if job is None:
        return None
    try:
        result = request_protocol_recommendation(job)
        recommendation = save_protocol_recommendation(job, result)
    except ProtocolRecommendationError as error:
        fail_protocol_ai_job(job.pk, str(error))
        return job.pk
    except RequestException as error:
        logger.error(
            f"Luma request failed: job_id={job.pk} "
            f"reason=request_error error_type={type(error).__name__}",
            exc_info=True,
        )
        fail_protocol_ai_job(job.pk, LUMA_UNAVAILABLE)
        return job.pk
    except IntegrityError:
        logger.error(
            f"Protocol recommendation save failed: job_id={job.pk}",
            exc_info=True,
        )
        fail_protocol_ai_job(job.pk, RECOMMENDATION_SAVE_FAILED)
        return job.pk
    except Exception as error:
        logger.error(
            f"Protocol recommendation failed: job_id={job.pk} "
            f"error_type={type(error).__name__}",
            exc_info=True,
        )
        fail_protocol_ai_job(job.pk, RECOMMENDATION_SAVE_FAILED)
        return job.pk
    if recommendation is None:
        fail_protocol_ai_job(job.pk, RECOMMENDATION_SAVE_FAILED)
    return job.pk


def reclaim_stale_protocol_ai_jobs() -> None:
    cutoff = timezone.localtime() - STALE_PROTOCOL_AI_PROCESSING
    ProtocolAiJob.objects.filter(
        status=ProtocolAiJobStatus.PROCESSING,
        updated_at__lt=cutoff,
        attempt_count__gt=0,
    ).update(
        status=ProtocolAiJobStatus.PENDING,
        attempt_count=F("attempt_count") - 1,
        error_detail="",
        updated_at=timezone.localtime(),
    )


def process_pending_protocol_ai_jobs(
    *,
    limit: int = 1,
    job_id: UUID | None = None,
) -> list[UUID | None]:
    reclaim_stale_protocol_ai_jobs()
    if job_id is not None:
        return [process_protocol_ai_job(job_id)]
    pending_job_ids = list(
        ProtocolAiJob.objects.filter(
            status__in=[ProtocolAiJobStatus.PENDING, ProtocolAiJobStatus.FAILED],
            attempt_count__lt=MAX_PROTOCOL_AI_ATTEMPTS,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    return [
        process_protocol_ai_job(pending_job_id) for pending_job_id in pending_job_ids
    ]


def assert_item_open(item: AiRecommendationItem) -> None:
    if item.decision not in OPEN_AI_RECOMMENDATION_DECISIONS:
        bad_request(ITEM_ALREADY_DECIDED)


def copied_until_modified(source_name: str) -> Case:
    return Case(
        When(
            decision=AiRecommendationItemDecision.PENDING,
            then=F(source_name),
        ),
        default=F(f"final_{source_name}"),
    )


def open_recommendation_item(item: AiRecommendationItem):
    return AiRecommendationItem.objects.filter(
        pk=item.pk,
        decision__in=OPEN_AI_RECOMMENDATION_DECISIONS,
        recommendation__status=AiRecommendationStatus.UNDER_REVIEW,
    )


def accept_recommendation_item(item: AiRecommendationItem) -> AiRecommendationItem:
    assert_item_open(item)
    updated = open_recommendation_item(item).update(
        decision=AiRecommendationItemDecision.ACCEPTED,
        final_dosage=copied_until_modified("dosage"),
        final_frequency=copied_until_modified("frequency"),
        final_custom_frequency=copied_until_modified("custom_frequency"),
        final_timing=copied_until_modified("timing"),
        final_duration=copied_until_modified("duration"),
        final_instructions=copied_until_modified("instructions"),
        final_rationale=copied_until_modified("rationale"),
        updated_at=timezone.localtime(),
    )
    if updated == 0:
        bad_request(ITEM_ALREADY_DECIDED)
    item.refresh_from_db()
    return item


def reject_recommendation_item(
    item: AiRecommendationItem,
    reason: str,
) -> AiRecommendationItem:
    assert_item_open(item)
    updated = open_recommendation_item(item).update(
        decision=AiRecommendationItemDecision.REJECTED,
        reason=reason,
        updated_at=timezone.localtime(),
    )
    if updated == 0:
        bad_request(ITEM_ALREADY_DECIDED)
    item.refresh_from_db()
    return item


def apply_recommendation_item_modification(
    item: AiRecommendationItem,
    validated_data: dict,
) -> AiRecommendationItem:
    assert_item_open(item)
    updated = open_recommendation_item(item).update(
        decision=AiRecommendationItemDecision.MODIFIED,
        final_dosage=validated_data["dosage"],
        final_frequency=validated_data["frequency"],
        final_custom_frequency=validated_data["custom_frequency"],
        final_timing=validated_data["timing"],
        final_duration=validated_data["duration"],
        final_instructions=validated_data["instructions"],
        final_rationale=F("rationale"),
        reason=validated_data["reason"],
        updated_at=timezone.localtime(),
    )
    if updated == 0:
        bad_request(ITEM_ALREADY_DECIDED)
    item.refresh_from_db()
    return item


def accepted_dose_complete(item: AiRecommendationItem) -> bool:
    required_values = (
        item.final_dosage,
        item.final_frequency,
        item.final_timing,
        item.final_duration,
        item.final_instructions,
        item.final_rationale,
    )
    return all(required_values)


def accepted_item_event_after(item: AiRecommendationItem) -> dict:
    return {
        "supplement_id": str(item.supplement_id),
        "dosage": item.final_dosage,
        "frequency": item.final_frequency,
        "custom_frequency": item.final_custom_frequency,
        "timing": item.final_timing,
        "duration": item.final_duration,
        "instructions": item.final_instructions,
        "rationale": item.final_rationale,
    }


def draft_protocol_items(
    version: ProtocolVersion,
    accepted_items: list[AiRecommendationItem],
) -> list[ProtocolItem]:
    return [
        ProtocolItem(
            version=version,
            supplement_id=item.supplement_id,
            dosage=item.final_dosage,
            frequency=item.final_frequency,
            custom_frequency=item.final_custom_frequency,
            timing=item.final_timing,
            duration=item.final_duration,
            instructions=item.final_instructions,
            rationale=item.final_rationale,
        )
        for item in accepted_items
    ]


def draft_protocol_events(
    protocol: Protocol,
    version: ProtocolVersion,
    actor: User,
    accepted_items: list[AiRecommendationItem],
) -> list[ProtocolEvent]:
    events = [
        ProtocolEvent(
            customer_profile_id=protocol.customer_profile_id,
            protocol=protocol,
            protocol_version=version,
            actor=actor,
            action=ProtocolEventAction.PROTOCOL_CREATED,
            after={"name": protocol.name, "purpose": protocol.purpose},
            client_visible=False,
        ),
        ProtocolEvent(
            customer_profile_id=protocol.customer_profile_id,
            protocol=protocol,
            protocol_version=version,
            actor=actor,
            action=ProtocolEventAction.VERSION_DRAFTED,
            after={
                "version_number": version.version_number,
                "status": version.status,
            },
            client_visible=False,
        ),
    ]
    events.extend(
        ProtocolEvent(
            customer_profile_id=protocol.customer_profile_id,
            protocol=protocol,
            protocol_version=version,
            actor=actor,
            action=ProtocolEventAction.SUPPLEMENT_ADDED,
            after=accepted_item_event_after(item),
            client_visible=False,
        )
        for item in accepted_items
    )
    return events


def recommendation_still_has_open_items():
    return AiRecommendationItem.objects.filter(
        recommendation=OuterRef("pk"),
        decision__in=OPEN_AI_RECOMMENDATION_DECISIONS,
    )


def claim_recommendation_for_draft(recommendation_id):
    return (
        AiRecommendation.objects.filter(
            pk=recommendation_id,
            status=AiRecommendationStatus.UNDER_REVIEW,
            protocol_version__isnull=True,
        )
        .exclude(Exists(recommendation_still_has_open_items()))
        .update(
            status=AiRecommendationStatus.APPLIED,
            updated_at=timezone.localtime(),
        )
    )


def reject_unclaimed_protocol_draft(recommendation: AiRecommendation):
    current = AiRecommendation.objects.filter(pk=recommendation.pk).first()
    if (
        current is None
        or current.status != AiRecommendationStatus.UNDER_REVIEW
        or current.protocol_version_id is not None
    ):
        bad_request(DRAFT_ALREADY_CREATED)
    if AiRecommendationItem.objects.filter(
        recommendation=recommendation,
        decision__in=OPEN_AI_RECOMMENDATION_DECISIONS,
    ).exists():
        bad_request(DRAFT_UNDECIDED)
    bad_request(DRAFT_ALREADY_CREATED)


def create_protocol_draft(
    recommendation: AiRecommendation,
    actor: User,
) -> ProtocolVersion:
    if recommendation.status != AiRecommendationStatus.UNDER_REVIEW:
        bad_request(DRAFT_ALREADY_CREATED)
    if recommendation.protocol_version_id is not None:
        bad_request(DRAFT_ALREADY_CREATED)
    with transaction.atomic():
        claimed = claim_recommendation_for_draft(recommendation.pk)
        if claimed == 0:
            reject_unclaimed_protocol_draft(recommendation)
        items = list(
            AiRecommendationItem.objects.filter(
                recommendation=recommendation,
            ).select_related("supplement")
        )
        accepted_items = [
            item
            for item in items
            if item.decision == AiRecommendationItemDecision.ACCEPTED
        ]
        if not accepted_items:
            bad_request(DRAFT_NONE_ACCEPTED)
        if any(not accepted_dose_complete(item) for item in accepted_items):
            bad_request(DRAFT_MISSING_DOSE)
        if any(not item.supplement.is_active for item in accepted_items):
            bad_request(INACTIVE_SUPPLEMENT_DETAIL)
        protocol = Protocol.objects.create(
            customer_profile=recommendation.customer_profile,
            name=recommendation.name,
            purpose=recommendation.purpose,
            created_by=actor,
        )
        version = ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
            notes=recommendation.notes,
            summary_notes=None,
            is_ongoing=False,
        )
        ProtocolItem.objects.bulk_create(draft_protocol_items(version, accepted_items))
        ProtocolEvent.objects.bulk_create(
            draft_protocol_events(protocol, version, actor, accepted_items)
        )
        AiRecommendation.objects.filter(pk=recommendation.pk).update(
            protocol_version=version,
            updated_at=timezone.localtime(),
        )
    return version
