from django.urls import path

from wearables.views import (
    DeviceConnectView,
    DeviceConsentRevokeView,
    DeviceDisconnectView,
    DeviceListView,
    DeviceSDKConfigView,
    DeviceRetrySyncView,
    NativeDeviceStatusView,
)

urlpatterns = [
    path("", DeviceListView.as_view(), name="wearable-device-list"),
    path("connect/", DeviceConnectView.as_view(), name="wearable-device-connect"),
    path("revoke-consent/", DeviceConsentRevokeView.as_view(), name="wearable-consent-revoke"),
    path(
        "disconnect/",
        DeviceDisconnectView.as_view(),
        name="wearable-device-disconnect",
    ),
    path("retry-sync/", DeviceRetrySyncView.as_view(), name="wearable-device-retry-sync"),
    path("sdk-config/", DeviceSDKConfigView.as_view(), name="wearable-sdk-config"),
    path(
        "native-status/",
        NativeDeviceStatusView.as_view(),
        name="wearable-native-status",
    ),
]

