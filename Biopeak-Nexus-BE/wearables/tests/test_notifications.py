from types import SimpleNamespace
from unittest import TestCase

from wearables.services.notifications import (
    apply_notification_state,
    notification_data_source,
    notification_text,
)
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    HistoricalImportStatus,
)


class NotificationNormalizationTests(TestCase):
    def test_authorization_completed_does_not_authorize_from_notification_text(self):
        connection = SimpleNamespace(
            status=ConnectionStatus.AUTHORIZING,
            authorization_status=AuthorizationStatus.PENDING,
            import_status=HistoricalImportStatus.NOT_STARTED,
            connected_at=None,
        )

        text = notification_text({"event_type": "authorization_completed"})
        apply_notification_state(connection, text)

        self.assertEqual(connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(
            connection.authorization_status,
            AuthorizationStatus.PENDING,
        )

    def test_provider_name_is_canonicalized(self):
        self.assertEqual(
            notification_data_source({"data_source": "garmin"}),
            "Garmin",
        )

    def test_rook_user_connected_does_not_authorize_or_start_import_from_text(self):
        connection = SimpleNamespace(
            status=ConnectionStatus.AUTHORIZING,
            authorization_status=AuthorizationStatus.PENDING,
            import_status=HistoricalImportStatus.NOT_STARTED,
            import_started_at=None, connected_at=None,
        )
        text = notification_text({"action": "user_connected", "message": "A user linked a wearable"})
        apply_notification_state(connection, text)
        self.assertEqual(connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(connection.authorization_status, AuthorizationStatus.PENDING)
        self.assertEqual(connection.import_status, HistoricalImportStatus.NOT_STARTED)

    def test_already_authorized_connected_notification_is_idempotent(self):
        connection = SimpleNamespace(
            status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            import_status=HistoricalImportStatus.COMPLETED,
            last_successful_sync=None,
        )
        apply_notification_state(connection, "user connected")
        self.assertEqual(connection.status, ConnectionStatus.ACTIVE)
        self.assertEqual(connection.authorization_status, AuthorizationStatus.AUTHORIZED)
