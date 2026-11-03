from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from accounts.verifications.views import DirectPhoneLoginView


class DirectPhoneLoginTests(TestCase):
    def test_invalid_bearer_does_not_block_login(self):
        request = APIRequestFactory().post(
            "/auth/login-phone-direct/",
            {"phone": "+91-9999999990"},
            format="json",
            HTTP_AUTHORIZATION="Bearer not-a-jwt",
        )
        response = DirectPhoneLoginView.as_view()(request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(response.data["detail"]["phone"][0]),
            "Phone number is not registered.",
        )
