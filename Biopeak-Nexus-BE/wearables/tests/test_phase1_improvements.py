"""Phase 1 regressions: pure policies plus actual PostgreSQL workflow tests."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from wearables.models import (
    HealthDailySummary, RookOutbox, WearableConnectionEvent,
)
from wearables.services.authorization_jobs import (
    process_authorise_rook_connection,
    process_revoke_rook_connection,
)
from wearables.services.authorization_tracking import record_authorization_grant
from wearables.services.client import RookClient, RookServiceError
from wearables.services.connections import (
    connection_actions,
    disconnect_connection,
    serialize_connection,
    start_connection,
)
from wearables.services.ingestion import ingest_rook_document, normalize_health_document
from wearables.services.analytics import MAX_LIFETIME_HISTORY_DAYS, domain_payload, member_today
from wearables.services.job_claims import (
    claim_health_job,
    defer_health_job,
    fail_health_job,
)
from wearables.services.job_queue import enqueue_authorise_rook_connection
from wearables.services.notifications import stale_rook_notification
from wearables.services.progress_policy import (
    domain_sync_progress,
    failure_recovery_action,
    revocation_confirmation_policy,
    sync_operation_state,
    sync_unit_progress,
)
from wearables.services.recovery import process_fetch_rook_data
from wearables.services.sync_plan import (
    advance_sync_plan,
    create_sync_plan,
    remaining_sync_units,
)
from wearables.tests import test_manager_flows as manager_tests
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    HealthJobStatus,
    HealthJobType,
    HealthDomain,
    MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
)

NOW = datetime(2026, 11, 10, 10, tzinfo=UTC)


class PhaseOneProgressPolicyTests(SimpleTestCase):
    def plan(self):
        return create_sync_plan(requested_at=NOW, timezone_name="Asia/Kolkata",
                                previous_cursor=None, flow="initial")

    def test_initial_window_has_twenty_one_request_units(self):
        self.assertEqual(sync_unit_progress(self.plan()), {"checkedUnits": 0, "totalUnits": 21})

    def test_counts_are_request_checks_not_history_percentages(self):
        plan = self.plan()
        for day, pillar in list(remaining_sync_units(plan))[:9]:
            plan = advance_sync_plan(plan, summary_date=day, pillar=pillar, document_count=0)
        self.assertEqual(sync_unit_progress(plan), {"checkedUnits": 9, "totalUnits": 21})
        domains = domain_sync_progress(plan=plan, operation_state="processing", observed_domains={"sleep"}, new_domains=set())
        self.assertEqual([item["domain"] for item in domains], ["sleep", "activity", "heart", "recovery", "body", "workouts"])
        self.assertTrue(domains[0]["hasStoredMeasurements"])
        self.assertNotIn("percentage", domains[0])

    def test_waiting_budget_is_distinct_from_no_measurements(self):
        state = sync_operation_state(
            status="pending",
            payload={"result": {"reason": "provider_429"}},
            attempts=0,
            maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
            scheduled_at=NOW + timedelta(minutes=1),
            now=NOW,
        )
        self.assertEqual(state, "waiting")

    def test_retryable_failure_is_automatic_wait(self):
        self.assertEqual(
            sync_operation_state(
                status="failed",
                payload={},
                attempts=1,
                maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                scheduled_at=NOW,
                now=NOW,
            ),
            "waiting",
        )

    def test_exhausted_failure_requires_action(self):
        self.assertEqual(
            sync_operation_state(
                status="failed",
                payload={},
                attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                scheduled_at=NOW,
                now=NOW,
            ),
            "failed",
        )

    def test_empty_check_is_not_new_data(self):
        self.assertEqual(
            sync_operation_state(
                status="completed",
                payload={"result": {"newObservationCount": 0}},
                attempts=1,
                maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                scheduled_at=NOW,
                now=NOW,
            ),
            "completed_no_new_data",
        )

    def test_old_completed_job_does_not_invent_empty_result(self):
        self.assertEqual(
            sync_operation_state(
                status="completed",
                payload={"result": {}},
                attempts=1,
                maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                scheduled_at=NOW,
                now=NOW,
            ),
            "completed",
        )

    def test_disabled_import_is_skipped_not_successful_check(self):
        self.assertEqual(
            sync_operation_state(
                status="completed",
                payload={"result": {"skipped": True}},
                attempts=1,
                maximum_attempts=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                scheduled_at=NOW,
                now=NOW,
            ),
            "skipped",
        )

    def test_withings_overnight_delay_is_expected(self):
        result = revocation_confirmation_policy(provider="Withings", requested_at=NOW-timedelta(hours=12), now=NOW)
        self.assertFalse(result["expired"])
        self.assertEqual(result["retryAfterSeconds"], 900)

    def test_withings_deadline_remains_bounded(self):
        self.assertTrue(revocation_confirmation_policy(provider="Withings", requested_at=NOW-timedelta(hours=48), now=NOW)["expired"])

    def test_other_provider_deadline_is_preserved(self):
        self.assertTrue(revocation_confirmation_policy(provider="Garmin", requested_at=NOW-timedelta(minutes=30), now=NOW)["expired"])

    def test_server_credentials_require_support_not_user_reconnect(self):
        self.assertEqual(failure_recovery_action(job_type="fetch_rook_data", status_code=401), "contact_support")

    def test_failed_authorization_can_be_retried_by_user(self):
        self.assertEqual(failure_recovery_action(job_type="authorise_rook_connection", status_code=502), "reconnect")

    @patch("wearables.services.client.requests.get")
    @patch("wearables.services.client.shared_summary_cache")
    def test_shared_summary_hit_avoids_another_provider_request(self, cache, request):
        cache.return_value.get.return_value = [{"user_id": "same-member", "document_version": 1}]
        client = RookClient()
        self.assertEqual(client.get_processed_summaries(rook_user_id="same-member", health_pillar="sleep",
                                                      summary_date="2026-11-10"), cache.return_value.get.return_value)
        request.assert_not_called()

    @patch("wearables.services.client.RookClient.before_request")
    @patch("wearables.services.client.requests.get")
    @patch("wearables.services.client.shared_summary_cache")
    def test_cache_outage_falls_back_to_direct_request(self, cache, request, admission):
        cache.return_value.get.side_effect = OSError("cache unavailable")
        request.return_value.status_code = 200
        request.return_value.content = b"document"
        request.return_value.json.return_value = {"user_id": "same-member", "document_version": 1}
        client = RookClient()
        self.assertEqual(len(client.get_processed_summaries(rook_user_id="same-member", health_pillar="sleep",
                                                          summary_date="2026-11-10")), 1)
        admission.assert_called_once()
        request.assert_called_once()

    @patch("wearables.services.client.RookClient.before_request")
    @patch("wearables.services.client.requests.get")
    @patch("wearables.services.client.shared_summary_cache")
    def test_empty_pull_is_never_cached_as_no_measurements(self, cache, request, admission):
        cache.return_value.get.return_value = None
        request.return_value.status_code = 204
        request.return_value.content = b""
        self.assertEqual(RookClient().get_processed_summaries(rook_user_id="same-member", health_pillar="sleep",
                                                            summary_date="2026-11-10"), [])
        cache.return_value.set.assert_not_called()

    @patch("wearables.services.notifications.authorization_granted_at", return_value=NOW-timedelta(days=1))
    @patch("wearables.services.notifications.WearableConnectionEvent")
    def test_normal_sync_timestamp_cannot_hide_valid_revoke(self, events, granted):
        events.objects.filter.return_value.order_by.return_value.__getitem__.return_value = []
        connection = SimpleNamespace(authorization_status=AuthorizationStatus.AUTHORIZED, import_started_at=NOW)
        self.assertFalse(stale_rook_notification(connection=connection, action_datetime=NOW-timedelta(minutes=5), text="authorization revoked"))

    @patch("wearables.services.notifications.authorization_granted_at", return_value=NOW)
    def test_event_from_previous_authorization_is_ignored(self, granted):
        connection = SimpleNamespace(authorization_status=AuthorizationStatus.AUTHORIZED)
        self.assertTrue(stale_rook_notification(connection=connection, action_datetime=NOW-timedelta(minutes=5), text="authorization revoked"))


@override_settings(ROOK_PREEXISTING_ENABLED=True, ROOK_SYNC_UNITS_PER_RUN=21,
                   ROOK_AUTH_OUTBOX_QUEUE_URL="", ROOK_DATA_FETCH_OUTBOX_QUEUE_URL="")
class PhaseOneImprovementDatabaseTests(TestCase):
    setUp = manager_tests.ManagerFlowTests.setUp
    queued_sync = manager_tests.ManagerFlowTests.queued_sync

    def pending_authorization(self):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save()
        return enqueue_authorise_rook_connection(connection=self.connection)

    def test_exhausted_authorization_has_recovery_action(self):
        queued = self.pending_authorization()
        claimed = claim_health_job(queued.pk)
        fail_health_job(claimed, RookServiceError("unavailable"), terminal=True)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.PROVIDER_ERROR)
        self.assertEqual(connection_actions(self.connection)[0]["id"], "reconnect")

    def test_legacy_exhausted_check_leaves_pending_state(self):
        queued = self.pending_authorization()
        RookOutbox.objects.filter(pk=queued.pk).update(status=HealthJobStatus.FAILED, attempt_count=1)
        enqueue_authorise_rook_connection(connection=self.connection)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.last_error_code, "authorization_verification_failed")

    @patch("wearables.services.connections.prepare_connection")
    @patch("wearables.services.connections.RookClient")
    def test_explicit_connect_after_exhaustion_uses_new_generation(self, client, prepare):
        queued = self.pending_authorization()
        old_generation = self.connection.authorization_generation
        RookOutbox.objects.filter(pk=queued.pk).update(status=HealthJobStatus.FAILED, attempt_count=1)
        prepare.return_value = self.connection
        client.return_value.get_authorized_sources.return_value = set()
        client.return_value.get_authorizer.return_value = {"authorized": False, "authorization_url": "https://connect.garmin.com/authorize"}
        result = start_connection(request=SimpleNamespace(user=self.user), customer_profile=self.profile,
                                  validated_data={"data_source": "Garmin", "consent_version": "v1", "historical_days": 7})
        self.assertNotEqual(result["connection"].authorization_generation, old_generation)
        self.assertFalse(RookOutbox.objects.filter(
            status=HealthJobStatus.PENDING,
            job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
        ).exists())

    @patch("wearables.services.authorization_jobs.RookClient")
    def test_user_not_yet_created_waits_for_authorization(self, client):
        client.return_value.get_authorized_sources.side_effect = RookServiceError("not created", status_code=422)
        claimed = claim_health_job(self.pending_authorization().pk)
        self.assertEqual(process_authorise_rook_connection(claimed)["reason"], "authorization_pending")

    def test_new_authorization_epoch_does_not_move_when_sync_starts(self):
        record_authorization_grant(self.connection)
        grant = WearableConnectionEvent.objects.get(event_type="authorization_granted")
        self.queued_sync()
        record_authorization_grant(self.connection)
        self.assertEqual(WearableConnectionEvent.objects.get(event_type="authorization_granted").pk, grant.pk)

    @patch("wearables.services.authorization_jobs.RookClient")
    def test_withings_wait_does_not_spend_failure_attempt(self, client):
        self.connection.data_source = "Withings"
        self.connection.save()
        disconnect_connection(customer_profile=self.profile, data_source="Withings", actor_user=self.user)
        queued = RookOutbox.objects.get(job_type=HealthJobType.REVOKE_ROOK_CONNECTION)
        queued.payload["revocationRequestedAt"] = (timezone.localtime()-timedelta(hours=2)).isoformat()
        queued.save()
        claimed = claim_health_job(queued.pk)
        client.return_value.get_authorized_sources.return_value = {"Withings"}
        result = process_revoke_rook_connection(claimed)
        self.assertTrue(result["deferred"])
        defer_health_job(claimed, result)
        queued.refresh_from_db()
        self.assertEqual(queued.attempt_count, 0)
        client.return_value.revoke_source.assert_not_called()

    @patch("wearables.services.recovery.RookClient")
    def test_empty_pull_keeps_original_measurement_time(self, client):
        observed_at = timezone.localtime()-timedelta(days=2)
        payload = {"user_id": self.identity.rook_user_id, "datetime": observed_at.isoformat(),
                   "data_structure": "physical_health_summary", "document_version": 1,
                   "source_of_data_string": "Garmin", "accumulated_steps_int": 5000}
        document = ingest_rook_document(payload, signature_valid=True)
        normalize_health_document(document["documentId"])
        client.return_value.get_processed_summaries.return_value = []
        result = process_fetch_rook_data(claim_health_job(self.queued_sync().pk))
        self.connection.refresh_from_db()
        response = serialize_connection(self.connection)
        self.assertEqual(result["newObservationCount"], 0)
        self.assertEqual(response["latestMeasurementAt"], observed_at)
        self.assertIsNotNone(response["lastCheckedAt"])
        self.assertEqual(response["syncProgress"]["status"], "completed_no_new_data")

    def test_superseded_authorization_failure_cannot_reopen_disconnect(self):
        claimed = claim_health_job(self.pending_authorization().pk)
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        self.assertFalse(fail_health_job(claimed, RookServiceError("late"), terminal=True))
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)

    @patch("wearables.services.analytics.build_domain_card", return_value={})
    def test_lifetime_window_excludes_rows_older_than_maximum(self, _card):
        today = member_today(self.profile)
        old_day = today - timedelta(days=MAX_LIFETIME_HISTORY_DAYS)
        new_day = today - timedelta(days=2)
        for day, steps in ((old_day, 9000), (new_day, 5000)):
            HealthDailySummary.objects.create(
                customer_profile=self.profile, domain=HealthDomain.ACTIVITY,
                metric="steps", local_date=day, source_key="lifetime-source", unit="steps",
                count=1, minimum=steps, maximum=steps, average=steps, total=steps, latest=steps,
            )
        activity = domain_payload(
            customer_profile=self.profile, domain=HealthDomain.ACTIVITY,
            days=90, window="lifetime",
        )
        metric = next(row for row in activity["metrics"] if row["metric"] == "steps")
        self.assertEqual(activity["historyWindowDays"], MAX_LIFETIME_HISTORY_DAYS)
        self.assertEqual([point["date"] for point in metric["points"]], [new_day])
        self.assertEqual(metric["rollingAverages"]["lifetime"]["observationDays"], 1)

        week = domain_payload(
            customer_profile=self.profile, domain=HealthDomain.ACTIVITY,
            days=7, window="7d",
        )
        week_metric = next(row for row in week["metrics"] if row["metric"] == "steps")
        self.assertEqual(week["historyWindowDays"], 7)
        self.assertEqual([point["date"] for point in week_metric["points"]], [new_day])
        self.assertFalse(week_metric["rollingAverages"]["lifetime"]["available"])
        self.assertFalse(week_metric["rollingAverages"]["14d"]["available"])

        for index, day in enumerate((old_day, new_day)):
            instant = timezone.now() - timedelta(days=index)
            HealthDailySummary.objects.create(
                customer_profile=self.profile, domain=HealthDomain.SLEEP,
                metric="sleep_start_time", local_date=day, source_key="lifetime-sleep-source",
                unit="ISO-8601", first_observed_at=instant, last_observed_at=instant,
                contributions={
                    f"lifetime-test-{index}-{self.profile.pk}": {
                        "v": 1, "u": "ISO-8601", "n": 0, "s": 0.0,
                        "tv": f"{day.isoformat()}T23:00:00Z", "at": instant.isoformat(),
                        "ds": ["Garmin"], "cf": 1.0,
                    },
                },
            )
        sleep = domain_payload(
            customer_profile=self.profile, domain=HealthDomain.SLEEP,
            days=90, window="lifetime",
        )
        self.assertEqual(len(sleep["sleepSessions"]), 1)
        self.assertEqual(sleep["sleepSessions"][0]["date"], new_day)
