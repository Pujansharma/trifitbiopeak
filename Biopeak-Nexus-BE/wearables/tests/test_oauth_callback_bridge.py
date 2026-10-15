"""Browser callback bridge tests (no database, OAuth secrets, or ROOK network)."""

from django.test import SimpleTestCase
from django.urls import resolve, reverse


class RookMobileCallbackBridgeTests(SimpleTestCase):
    client_uuid = "f2f2e6d2-1467-4ecc-bb4d-9bfc1249458e"
    rook_user_id = "bp-user-123"

    def test_base_url_redirects_to_app_without_authentication(self) -> None:
        response = self.client.get("/rook/return")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "biopeak://oauth-callback")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_trailing_slash_is_also_supported(self) -> None:
        response = self.client.get("/rook/return/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "biopeak://oauth-callback")

    def test_rook_appended_identifiers_are_passed_as_navigation_context(self) -> None:
        response = self.client.get(
            f"/rook/return/client_uuid/{self.client_uuid}/user_id/{self.rook_user_id}",
            {"status": "connected", "ignore": "https://example.com/redirect"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "biopeak://oauth-callback?"
            f"client_uuid={self.client_uuid}&user_id={self.rook_user_id}&status=connected",
        )
        self.assertNotIn("ignore", response["Location"])
        self.assertNotIn("example.com", response["Location"])

    def test_appended_path_accepts_trailing_slash(self) -> None:
        response = self.client.get(
            f"/rook/return/client_uuid/{self.client_uuid}/user_id/{self.rook_user_id}/"
        )
        self.assertEqual(response.status_code, 302)

    def test_rejects_invalid_client_uuid_and_user_identifier(self) -> None:
        invalid_uuid = self.client.get(
            f"/rook/return/client_uuid/not-a-uuid/user_id/{self.rook_user_id}"
        )
        self.assertEqual(invalid_uuid.status_code, 400)
        invalid_user = self.client.get(
            f"/rook/return/client_uuid/{self.client_uuid}/user_id/invalid_user"
        )
        self.assertEqual(invalid_user.status_code, 400)

    def test_forwards_only_limited_status_and_error(self) -> None:
        response = self.client.get(
            "/rook/return",
            {"error": "invalid&token=SECRET", "status": "pending", "redirect_url": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "biopeak://oauth-callback?status=pending&error=invalid%26token%3DSECRET",
        )
        self.assertNotIn("attacker.example", response["Location"])

    def test_rejects_non_get_request(self) -> None:
        response = self.client.post("/rook/return")
        self.assertEqual(response.status_code, 405)

    def test_existing_stateful_route_stays_registered(self) -> None:
        match = resolve(
            f"/r/AAAAAAAAAAAAAAAA/client_uuid/{self.client_uuid}/user_id/{self.rook_user_id}"
        )
        self.assertEqual(match.url_name, "rook-oauth-return")
