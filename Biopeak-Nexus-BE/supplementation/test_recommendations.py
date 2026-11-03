import json
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from requests import ConnectionError, RequestException, Response
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.users.utils.constants import Gender
from accounts.users.utils.helper import calculate_age
from accounts.utils.constants import UserType
from supplementation.models import (
    AiRecommendation,
    Brand,
    Protocol,
    ProtocolAiJob,
    ProtocolEvent,
    ProtocolItem,
    Supplement,
)
from supplementation.utils.constants import (
    AiRecommendationItemDecision,
    AiRecommendationItemOrigin,
    AiRecommendationStatus,
    ProtocolAiJobStatus,
    ProtocolEventAction,
    ProtocolVersionStatus,
    RawMaterialSourceType,
    SupplementForm,
)
from supplementation.utils.protocol_ai import (
    ProtocolRecommendationError,
    parse_protocol_recommendation,
    process_pending_protocol_ai_jobs,
    process_protocol_ai_job,
)
from supplementation.utils.protocol_ai_wake import publish_protocol_ai_wake
from supplementation.views import (
    AiRecommendationDetailView,
    AiRecommendationDraftView,
    AiRecommendationItemAcceptView,
    AiRecommendationItemModifyView,
    AiRecommendationItemRejectView,
    AiRecommendationListView,
    ProtocolAiQueueView,
)


def create_staff_user(email, account_type):
    user = User.objects.create_user(email=email)
    UserAccount.objects.create(user=user, account_type=account_type)
    return user


def create_profile(email, first_name, last_name):
    user = User.objects.create_user(email=email)
    customer = Customer.objects.create(user=user, contact_email=email)
    return CustomerProfile.objects.create(
        customer=customer,
        first_name=first_name,
        last_name=last_name,
        gender=Gender.FEMALE,
        date_of_birth=date(1990, 6, 15),
        is_main=True,
        is_active=True,
    )


def create_supplement(brand, product_name, sku, *, is_active=True):
    return Supplement.objects.create(
        brand=brand,
        product_name=product_name,
        form=SupplementForm.CAPSULE,
        sku=sku,
        manufacturer="Thorne",
        raw_material_source_type=RawMaterialSourceType.WHOLE_FOOD,
        pack_quantity_info="60 capsules",
        serving_size="1 capsule",
        serving_container=60,
        market_country_code="US",
        is_active=is_active,
    )


def ai_dose(supplement_id, *, dosage="1 capsule", origin="requested"):
    return {
        "supplement_id": supplement_id,
        "origin": origin,
        "dosage": dosage,
        "frequency": "daily",
        "custom_frequency": None,
        "timing": "with_dinner",
        "duration": "30 days",
        "instructions": "Take with dinner.",
        "rationale": "Low vitamin D.",
    }


LUMA_ERROR_RESPONSES = {
    401: ({"detail": "Invalid API key."}, "Luma rejected the Nexus API key."),
    404: ({"detail": "Client not found."}, "Luma could not find this client."),
    409: (
        {"detail": "Identity mismatch."},
        "Luma could not confirm this client's identity.",
    ),
    422: (
        {"detail": "No usable report data for this client."},
        "Luma could not build a recommendation for this client.",
    ),
    503: ({"detail": "LLM unavailable."}, "Luma is unavailable."),
    500: ({"error": "Internal error", "error_id": "err-1"}, "Luma is unavailable."),
}


def luma_response(status_code, body):
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.url = "http://luma.test/protocol-recommendation"
    return response


class ProtocolRecommendationParseTests(TestCase):
    def test_omitted_requested_supplement_fails(self):
        requested_id = uuid.uuid4()
        with self.assertRaisesMessage(
            ProtocolRecommendationError,
            "Luma omitted a requested supplement.",
        ):
            parse_protocol_recommendation(
                {"model": "gpt-4.1", "items": [ai_dose(str(uuid.uuid4()))]},
                {requested_id},
            )

    def test_unknown_extra_supplement_fails(self):
        requested_id = uuid.uuid4()
        extra_id = uuid.uuid4()
        with self.assertRaisesMessage(
            ProtocolRecommendationError,
            "Luma returned an unknown supplement.",
        ):
            parse_protocol_recommendation(
                {
                    "model": "gpt-4.1",
                    "items": [
                        ai_dose(str(requested_id)),
                        ai_dose(str(extra_id), origin="ai_added"),
                    ],
                },
                {requested_id},
            )


class ProtocolAiRecommendationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user("ai-admin@example.com", UserType.ADMIN)
        self.associate = create_staff_user(
            "ai-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "ai-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile("ai-ava@example.com", "Ava", "Shah")
        self.inactive_profile = create_profile(
            "ai-inactive@example.com",
            "Noah",
            "Kim",
        )
        self.inactive_profile.is_active = False
        self.inactive_profile.save(update_fields=["is_active", "updated_at"])
        brand = Brand.objects.create(name="AI Thorne")
        self.vitamin = create_supplement(brand, "Vitamin D3", "AI-D3")
        self.magnesium = create_supplement(brand, "Magnesium", "AI-MG")
        self.inactive_supplement = create_supplement(
            brand,
            "Old Fish Oil",
            "AI-FISH",
            is_active=False,
        )

    def queue(self, user, profile_id, body):
        request = self.factory.post(
            f"/supplementation/profiles/{profile_id}/protocols/ai/",
            body,
            format="json",
        )
        force_authenticate(request, user=user)
        return ProtocolAiQueueView.as_view()(request, profile_id=profile_id)

    def queue_body(self, supplement_ids=None):
        if supplement_ids is None:
            supplement_ids = [str(self.vitamin.pk)]
        return {
            "name": "Sleep & Recovery",
            "purpose": "Faster sleep onset",
            "notes": "",
            "supplement_ids": supplement_ids,
        }

    def saved_result(self, items):
        return {"model": "gpt-4.1", "items": items}

    def run_job(self, job, items):
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            return_value=self.saved_result(items),
        ):
            process_protocol_ai_job(job.pk)
        return AiRecommendation.objects.get(job=job)

    @patch("supplementation.serializers.publish_protocol_ai_wake")
    def test_queue_writes_pending_job(self, publish_wake):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.queue(self.admin, self.profile.pk, self.queue_body())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["detail"], "Protocol recommendation queued.")
        job = ProtocolAiJob.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(job.status, ProtocolAiJobStatus.PENDING)
        self.assertEqual(job.customer_profile_id, self.profile.pk)
        self.assertEqual(job.requested_by_id, self.admin.pk)
        self.assertEqual(job.supplement_ids, [self.vitamin.pk])
        self.assertEqual(Protocol.objects.count(), 0)
        publish_wake.assert_called_once_with(job.pk)

    def test_associate_can_queue(self):
        with patch("supplementation.serializers.publish_protocol_ai_wake"):
            response = self.queue(self.associate, self.profile.pk, self.queue_body())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_customer_cannot_queue(self):
        response = self.queue(self.customer, self.profile.pk, self.queue_body())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_profile_is_not_found(self):
        response = self.queue(
            self.admin,
            self.inactive_profile.pk,
            self.queue_body(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Customer profile not found.")

    def test_duplicate_or_inactive_supplement_is_rejected(self):
        duplicate = self.queue(
            self.admin,
            self.profile.pk,
            self.queue_body([str(self.vitamin.pk), str(self.vitamin.pk)]),
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supplement_ids", duplicate.data["detail"])
        inactive = self.queue(
            self.admin,
            self.profile.pk,
            self.queue_body([str(self.inactive_supplement.pk)]),
        )
        self.assertEqual(inactive.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Unknown or inactive supplement.", inactive.data["detail"]["supplement_ids"]
        )
        empty = self.queue(
            self.admin,
            self.profile.pk,
            self.queue_body([]),
        )
        self.assertEqual(empty.status_code, status.HTTP_400_BAD_REQUEST)

    def test_worker_saves_model_and_items(self):
        with patch("supplementation.serializers.publish_protocol_ai_wake"):
            queued = self.queue(
                self.admin,
                self.profile.pk,
                self.queue_body([str(self.vitamin.pk), str(self.magnesium.pk)]),
            )
        job = ProtocolAiJob.objects.get(pk=queued.data["data"]["id"])
        recommendation = self.run_job(
            job,
            [
                ai_dose(self.vitamin.pk),
                ai_dose(self.magnesium.pk, dosage="2 capsules"),
            ],
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ProtocolAiJobStatus.COMPLETED)
        self.assertEqual(recommendation.model, "gpt-4.1")
        self.assertEqual(recommendation.status, AiRecommendationStatus.UNDER_REVIEW)
        items = list(recommendation.items.order_by("created_at", "id"))
        self.assertEqual(items[0].origin, AiRecommendationItemOrigin.REQUESTED)
        self.assertEqual(items[1].supplement_id, self.magnesium.pk)
        self.assertEqual(items[1].dosage, "2 capsules")
        self.assertIsNone(items[0].final_dosage)

    def test_worker_failure_can_retry_until_max_attempts(self):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            side_effect=ProtocolRecommendationError("Luma is unavailable."),
        ) as request_recommendation:
            process_protocol_ai_job(job.pk)
            process_protocol_ai_job(job.pk)
            process_protocol_ai_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(request_recommendation.call_count, 2)
        self.assertEqual(job.status, ProtocolAiJobStatus.FAILED)
        self.assertEqual(job.attempt_count, 2)
        self.assertEqual(job.error_detail, "Luma is unavailable.")
        self.assertFalse(AiRecommendation.objects.filter(job=job).exists())

    def test_request_error_fails_that_job_and_continues(self):
        first = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )
        second = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            side_effect=[
                RequestException("connection reset"),
                self.saved_result([ai_dose(self.vitamin.pk)]),
            ],
        ):
            process_pending_protocol_ai_jobs(limit=2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ProtocolAiJobStatus.FAILED)
        self.assertEqual(first.attempt_count, 1)
        self.assertEqual(first.error_detail, "Luma is unavailable.")
        self.assertEqual(second.status, ProtocolAiJobStatus.COMPLETED)

    def test_unexpected_error_fails_that_job_and_continues(self):
        first = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )
        second = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            side_effect=[
                RuntimeError("boom"),
                self.saved_result([ai_dose(self.vitamin.pk)]),
            ],
        ):
            process_pending_protocol_ai_jobs(limit=2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ProtocolAiJobStatus.FAILED)
        self.assertEqual(first.error_detail, "Could not save the recommendation.")
        self.assertEqual(second.status, ProtocolAiJobStatus.COMPLETED)

    def test_one_run_calls_luma_for_one_job(self):
        first = self.create_job()
        second = self.create_job()
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            return_value=self.saved_result([ai_dose(self.vitamin.pk)]),
        ) as request_recommendation:
            process_pending_protocol_ai_jobs()
        self.assertEqual(request_recommendation.call_count, 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ProtocolAiJobStatus.COMPLETED)
        self.assertEqual(second.status, ProtocolAiJobStatus.PENDING)

    def test_job_id_calls_luma_for_that_job_only(self):
        first = self.create_job()
        second = self.create_job()
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            return_value=self.saved_result([ai_dose(self.vitamin.pk)]),
        ):
            call_command("process_protocol_ai_jobs", job_id=str(second.pk))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ProtocolAiJobStatus.PENDING)
        self.assertEqual(second.status, ProtocolAiJobStatus.COMPLETED)

    def test_invalid_job_id_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("process_protocol_ai_jobs", job_id="not-a-job")

    def test_stale_processing_job_is_retried_without_a_new_attempt(self):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
            status=ProtocolAiJobStatus.PROCESSING,
            attempt_count=1,
        )
        ProtocolAiJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.localtime() - timedelta(minutes=3),
        )
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
            return_value=self.saved_result([ai_dose(self.vitamin.pk)]),
        ):
            process_pending_protocol_ai_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, ProtocolAiJobStatus.COMPLETED)
        self.assertEqual(job.attempt_count, 1)

    def test_fresh_processing_job_is_left_alone(self):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
            status=ProtocolAiJobStatus.PROCESSING,
            attempt_count=1,
        )
        ProtocolAiJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.localtime() - timedelta(minutes=1),
        )
        with patch(
            "supplementation.utils.protocol_ai.request_protocol_recommendation",
        ) as request_recommendation:
            process_pending_protocol_ai_jobs()
        request_recommendation.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, ProtocolAiJobStatus.PROCESSING)
        self.assertEqual(job.attempt_count, 1)

    @override_settings(
        PROTOCOL_AI_WAKE_QUEUE_URL="https://sqs.ap-south-1.amazonaws.com/1/protocol-ai.fifo",
        AWS_REGION="ap-south-1",
    )
    @patch("supplementation.utils.protocol_ai_wake.boto3.client")
    def test_wake_message_names_that_job(self, boto_client):
        job_id = uuid.uuid4()
        publish_protocol_ai_wake(job_id)
        message = boto_client.return_value.send_message.call_args.kwargs
        self.assertEqual(
            message["MessageBody"],
            f"process_protocol_ai_jobs --job-id {job_id}",
        )
        self.assertEqual(message["MessageDeduplicationId"], str(job_id))
        self.assertEqual(message["MessageGroupId"], "protocol-ai-jobs")

    def create_job(self):
        return ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
        )

    @override_settings(
        LUMA_BASE_URL="http://luma.test",
        LUMA_NEXUS_API_KEY="nexus-key",
    )
    @patch("supplementation.utils.protocol_ai.Session")
    def test_luma_success_saves_model_and_items(self, session):
        CustomerProfile.objects.filter(pk=self.profile.pk).update(
            data={"metsights_profile_id": "ms-profile-1"},
        )
        job = self.create_job()
        session.return_value.post.return_value = luma_response(
            200,
            {"model": "gpt-6.1-sol", "items": [ai_dose(str(self.vitamin.pk))]},
        )
        process_protocol_ai_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, ProtocolAiJobStatus.COMPLETED)
        recommendation = AiRecommendation.objects.get(job=job)
        self.assertEqual(recommendation.model, "gpt-6.1-sol")
        self.assertEqual(recommendation.items.get().supplement_id, self.vitamin.pk)
        session.return_value.headers.update.assert_called_once_with(
            {"X-API-Key": "nexus-key"},
        )
        args, kwargs = session.return_value.post.call_args
        self.assertEqual(
            args[0],
            "http://luma.test/luma/v1/integrations/nexus/clients/"
            f"{self.profile.pk}/protocol-recommendation",
        )
        self.assertEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["json"]["customer_profile_id"], str(self.profile.pk))
        self.assertEqual(kwargs["json"]["metsights_profile_id"], "ms-profile-1")

    @override_settings(
        LUMA_BASE_URL="http://luma.test",
        LUMA_NEXUS_API_KEY="nexus-key",
    )
    @patch("supplementation.utils.protocol_ai.Session")
    def test_luma_error_status_fails_job_with_mapped_message(self, session):
        for status_code, (body, message) in LUMA_ERROR_RESPONSES.items():
            with self.subTest(status_code=status_code):
                job = self.create_job()
                session.return_value.post.return_value = luma_response(
                    status_code,
                    body,
                )
                process_protocol_ai_job(job.pk)
                job.refresh_from_db()
                self.assertEqual(job.status, ProtocolAiJobStatus.FAILED)
                self.assertEqual(job.error_detail, message)
                self.assertFalse(AiRecommendation.objects.filter(job=job).exists())

    @override_settings(
        LUMA_BASE_URL="http://luma.test",
        LUMA_NEXUS_API_KEY="nexus-key",
    )
    @patch("supplementation.utils.protocol_ai.Session")
    def test_luma_connection_error_fails_job(self, session):
        job = self.create_job()
        session.return_value.post.side_effect = ConnectionError()
        process_protocol_ai_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, ProtocolAiJobStatus.FAILED)
        self.assertEqual(job.error_detail, "Luma is unavailable.")

    @patch("supplementation.utils.protocol_ai.Session")
    def test_luma_not_configured_fails_job_without_a_call(self, session):
        blank_settings = (
            {"LUMA_BASE_URL": "", "LUMA_NEXUS_API_KEY": "nexus-key"},
            {"LUMA_BASE_URL": "http://luma.test", "LUMA_NEXUS_API_KEY": ""},
        )
        for settings_override in blank_settings:
            with self.subTest(blank=settings_override), override_settings(
                **settings_override
            ):
                job = self.create_job()
                process_protocol_ai_job(job.pk)
                job.refresh_from_db()
                self.assertEqual(job.status, ProtocolAiJobStatus.FAILED)
                self.assertEqual(job.error_detail, "Luma is not configured.")
        session.assert_not_called()

    def list_recommendations(self, user, **query):
        request = self.factory.get("/supplementation/ai-recommendations/", query)
        force_authenticate(request, user=user)
        return AiRecommendationListView.as_view()(request)

    def detail(self, user, recommendation_id):
        request = self.factory.get(
            f"/supplementation/ai-recommendations/{recommendation_id}/",
        )
        force_authenticate(request, user=user)
        return AiRecommendationDetailView.as_view()(request, pk=recommendation_id)

    def accept(self, user, item_id):
        request = self.factory.post(
            f"/supplementation/ai-recommendation-items/{item_id}/accept/",
            {},
            format="json",
        )
        force_authenticate(request, user=user)
        return AiRecommendationItemAcceptView.as_view()(request, pk=item_id)

    def reject(self, user, item_id, reason="Fish allergy."):
        request = self.factory.post(
            f"/supplementation/ai-recommendation-items/{item_id}/reject/",
            {"reason": reason},
            format="json",
        )
        force_authenticate(request, user=user)
        return AiRecommendationItemRejectView.as_view()(request, pk=item_id)

    def modify(self, user, item_id, body):
        request = self.factory.patch(
            f"/supplementation/ai-recommendation-items/{item_id}/",
            body,
            format="json",
        )
        force_authenticate(request, user=user)
        return AiRecommendationItemModifyView.as_view()(request, pk=item_id)

    def draft(self, user, recommendation_id):
        request = self.factory.post(
            f"/supplementation/ai-recommendations/{recommendation_id}/draft/",
            {},
            format="json",
        )
        force_authenticate(request, user=user)
        return AiRecommendationDraftView.as_view()(request, pk=recommendation_id)

    def saved_recommendation(self):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk, self.magnesium.pk],
        )
        return self.run_job(
            job,
            [
                ai_dose(self.vitamin.pk),
                ai_dose(self.magnesium.pk, dosage="2 capsules"),
            ],
        )

    def test_list_counts_search_and_status(self):
        recommendation = self.saved_recommendation()
        vitamin_item = recommendation.items.get(supplement=self.vitamin)
        magnesium_item = recommendation.items.get(supplement=self.magnesium)
        self.modify(
            self.admin,
            vitamin_item.pk,
            {
                "dosage": "2 capsules",
                "frequency": "daily",
                "custom_frequency": None,
                "timing": "with_lunch",
                "duration": "60 days",
                "instructions": "Take 2 capsules with lunch.",
                "reason": "Dose raised after the repeat panel.",
            },
        )
        pending = self.list_recommendations(
            self.admin,
            recommendation_status="pending",
            search="Shah",
        )
        self.assertEqual(pending.status_code, status.HTTP_200_OK)
        self.assertEqual(
            pending.data["detail"], "AI recommendations retrieved successfully."
        )
        row = pending.data["data"][0]
        self.assertEqual(row["id"], str(recommendation.job_id))
        self.assertEqual(row["customer_profile"]["name"], "Ava Shah")
        self.assertEqual(row["customer_profile"]["gender"], "Female")
        self.assertEqual(
            row["customer_profile"]["age"],
            calculate_age(date(1990, 6, 15)),
        )
        self.assertEqual(row["model"], "gpt-4.1")
        self.assertIsNone(row["error"])
        self.assertEqual(row["status"], "pending")
        self.assertEqual(
            row["recommendation"],
            {
                "id": str(recommendation.pk),
                "name": "Sleep & Recovery",
                "total": 2,
                "accepted": 0,
                "modified": 1,
                "rejected": 0,
            },
        )
        self.assertEqual(
            row["created_at"],
            timezone.localtime(recommendation.job.created_at).isoformat(),
        )
        self.reject(self.admin, magnesium_item.pk)
        self.accept(self.admin, vitamin_item.pk)
        completed = self.list_recommendations(
            self.admin,
            recommendation_status="completed",
        )
        self.assertEqual(completed.data["data"][0]["status"], "completed")
        self.assertEqual(completed.data["data"][0]["recommendation"]["accepted"], 1)
        self.assertEqual(completed.data["data"][0]["recommendation"]["modified"], 0)
        self.assertEqual(completed.data["data"][0]["recommendation"]["rejected"], 1)
        missed = self.list_recommendations(self.admin, search="Nobody")
        self.assertEqual(missed.data["data"], [])
        junk = self.list_recommendations(self.admin, recommendation_status="nope")
        self.assertEqual(junk.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(junk.data["detail"], "Invalid recommendation_status.")

    @patch("supplementation.serializers.publish_protocol_ai_wake")
    def test_list_shows_processing_job(self, publish_wake):
        with self.captureOnCommitCallbacks(execute=True):
            queued = self.queue(self.admin, self.profile.pk, self.queue_body())
        job_id = queued.data["data"]["id"]
        listed = self.list_recommendations(self.admin)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        row = listed.data["data"][0]
        self.assertEqual(row["id"], job_id)
        self.assertEqual(row["status"], "processing")
        self.assertIsNone(row["model"])
        self.assertIsNone(row["error"])
        self.assertEqual(
            row["recommendation"],
            {
                "id": None,
                "name": "Sleep & Recovery",
                "total": 0,
                "accepted": 0,
                "modified": 0,
                "rejected": 0,
            },
        )
        pending = self.list_recommendations(self.admin, recommendation_status="pending")
        self.assertEqual(pending.data["data"][0]["id"], job_id)
        processing = self.list_recommendations(
            self.admin,
            recommendation_status="processing",
        )
        self.assertEqual(processing.data["data"][0]["id"], job_id)
        completed = self.list_recommendations(
            self.admin,
            recommendation_status="completed",
        )
        self.assertEqual(completed.data["data"], [])
        failed = self.list_recommendations(self.admin, recommendation_status="failed")
        self.assertEqual(failed.data["data"], [])
        publish_wake.assert_called_once_with(uuid.UUID(job_id))

    def test_list_shows_failed_job(self):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.profile,
            requested_by=self.admin,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            supplement_ids=[self.vitamin.pk],
            status=ProtocolAiJobStatus.FAILED,
            error_detail="Luma is unavailable.",
            attempt_count=3,
        )
        listed = self.list_recommendations(self.admin, recommendation_status="failed")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        row = listed.data["data"][0]
        self.assertEqual(row["id"], str(job.pk))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "Luma is unavailable.")
        self.assertIsNone(row["recommendation"]["id"])
        self.assertIsNone(row["model"])
        pending = self.list_recommendations(self.admin, recommendation_status="pending")
        self.assertEqual(pending.data["data"], [])

    def test_detail_and_decisions_then_draft(self):
        recommendation = self.saved_recommendation()
        detail = self.detail(self.admin, recommendation.pk)
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["status"], "under_review")
        self.assertEqual(detail.data["data"]["protocol_version_id"], None)
        self.assertEqual(detail.data["data"]["pending_count"], 2)
        self.assertIsNone(detail.data["data"]["items"][0]["final_dosage"])
        items_by_product = {
            item["supplement"]["product_name"]: item
            for item in detail.data["data"]["items"]
        }
        vitamin_row = items_by_product["Vitamin D3"]
        self.assertNotIn("supplement_id", vitamin_row)
        self.assertEqual(
            vitamin_row["supplement"],
            {
                "id": str(self.vitamin.pk),
                "product_name": "Vitamin D3",
                "brand_name": "AI Thorne",
                "form": "capsule",
                "manufacturer": "Thorne",
            },
        )
        unknown = self.detail(self.admin, uuid.uuid4())
        self.assertEqual(unknown.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unknown.data["detail"], "AI recommendation not found.")

        vitamin_item = recommendation.items.get(supplement=self.vitamin)
        magnesium_item = recommendation.items.get(supplement=self.magnesium)
        blocked = self.draft(self.admin, recommendation.pk)
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            blocked.data["detail"],
            "Accept or reject every supplement before creating the draft.",
        )
        modified = self.modify(
            self.admin,
            vitamin_item.pk,
            {
                "dosage": "2 capsules",
                "frequency": "daily",
                "custom_frequency": None,
                "timing": "with_lunch",
                "duration": "60 days",
                "instructions": "Take 2 capsules with lunch.",
                "reason": "Dose raised after the repeat panel.",
            },
        )
        self.assertEqual(modified.status_code, status.HTTP_200_OK)
        self.assertNotIn("reason", modified.data["data"])
        self.assertNotIn("supplement_id", modified.data["data"])
        self.assertEqual(
            modified.data["data"]["supplement"]["id"],
            str(self.vitamin.pk),
        )
        self.assertEqual(modified.data["data"]["decision"], "modified")
        self.assertEqual(modified.data["data"]["dosage"], "1 capsule")
        self.assertEqual(modified.data["data"]["final_dosage"], "2 capsules")
        self.assertEqual(modified.data["data"]["final_timing"], "with_lunch")
        still_blocked = self.draft(self.admin, recommendation.pk)
        self.assertEqual(still_blocked.status_code, status.HTTP_400_BAD_REQUEST)
        accepted = self.accept(self.admin, vitamin_item.pk)
        self.assertEqual(accepted.data["data"]["decision"], "accepted")
        vitamin_item.refresh_from_db()
        self.assertEqual(vitamin_item.final_dosage, "2 capsules")
        self.assertEqual(vitamin_item.final_timing, "with_lunch")
        blank_reason = self.reject(self.admin, magnesium_item.pk, reason=" ")
        self.assertEqual(blank_reason.status_code, status.HTTP_400_BAD_REQUEST)
        rejected = self.reject(self.admin, magnesium_item.pk)
        self.assertEqual(rejected.data["data"]["decision"], "rejected")
        again = self.accept(self.admin, vitamin_item.pk)
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            again.data["detail"],
            "This item is already accepted or rejected.",
        )
        missing_item = self.accept(self.admin, uuid.uuid4())
        self.assertEqual(missing_item.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            missing_item.data["detail"],
            "AI recommendation item not found.",
        )

        created = self.draft(self.associate, recommendation.pk)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["detail"], "Protocol version created.")
        self.assertEqual(created.data["data"]["status"], ProtocolVersionStatus.DRAFT)
        protocol = Protocol.objects.get(pk=created.data["data"]["protocol_id"])
        self.assertEqual(protocol.name, "Sleep & Recovery")
        self.assertEqual(protocol.purpose, "Faster sleep onset")
        self.assertIsNone(protocol.current_version_id)
        version_items = list(ProtocolItem.objects.filter(version__protocol=protocol))
        self.assertEqual(len(version_items), 1)
        self.assertEqual(version_items[0].supplement_id, self.vitamin.pk)
        self.assertEqual(version_items[0].dosage, "2 capsules")
        self.assertEqual(version_items[0].timing, "with_lunch")
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, AiRecommendationStatus.APPLIED)
        self.assertEqual(
            str(recommendation.protocol_version_id),
            created.data["data"]["new_protocol_version_id"],
        )
        actions = set(
            ProtocolEvent.objects.filter(protocol=protocol).values_list(
                "action",
                flat=True,
            )
        )
        self.assertEqual(
            actions,
            {
                ProtocolEventAction.PROTOCOL_CREATED,
                ProtocolEventAction.VERSION_DRAFTED,
                ProtocolEventAction.SUPPLEMENT_ADDED,
            },
        )
        second = self.draft(self.admin, recommendation.pk)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            second.data["detail"],
            "A draft was already created from this recommendation.",
        )
        self.assertEqual(
            Protocol.objects.filter(customer_profile=self.profile).count(), 1
        )

    def test_all_rejected_items_cannot_create_a_draft(self):
        recommendation = self.saved_recommendation()
        for item in recommendation.items.all():
            self.reject(self.admin, item.pk)
        response = self.draft(self.admin, recommendation.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "Accept at least one supplement before creating the draft.",
        )
        self.assertEqual(Protocol.objects.count(), 0)

    def test_inactive_accepted_supplement_cannot_create_a_draft(self):
        recommendation = self.saved_recommendation()
        vitamin_item = recommendation.items.get(supplement=self.vitamin)
        magnesium_item = recommendation.items.get(supplement=self.magnesium)
        self.accept(self.admin, vitamin_item.pk)
        self.reject(self.admin, magnesium_item.pk)
        self.vitamin.is_active = False
        self.vitamin.save(update_fields=["is_active", "updated_at"])
        response = self.draft(self.admin, recommendation.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Supplement is inactive.")
        self.assertEqual(Protocol.objects.count(), 0)
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, AiRecommendationStatus.UNDER_REVIEW)
        self.assertIsNone(recommendation.protocol_version_id)

    def test_accept_without_modify_copies_the_ai_dose(self):
        recommendation = self.saved_recommendation()
        item = recommendation.items.get(supplement=self.vitamin)
        self.accept(self.admin, item.pk)
        item.refresh_from_db()
        self.assertEqual(item.decision, AiRecommendationItemDecision.ACCEPTED)
        self.assertEqual(item.final_dosage, item.dosage)
        self.assertEqual(item.final_frequency, item.frequency)
        self.assertEqual(item.final_timing, item.timing)
