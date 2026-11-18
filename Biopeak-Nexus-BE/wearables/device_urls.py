from django.urls import path

from wearables.views import (
    DeviceConnectView,
    DeviceProviderCatalogueView,
    DeviceDisconnectView,
    DeviceRetrySyncView,
    NativeDeviceStatusView,
)

urlpatterns = [
    path("connect/", DeviceConnectView.as_view(), name="wearable-device-connect"),
    path("providers/", DeviceProviderCatalogueView.as_view(), name="wearable-provider-catalogue"),
    path(
        "disconnect/",
        DeviceDisconnectView.as_view(),
        name="wearable-device-disconnect",
    ),
    path("sync/", DeviceRetrySyncView.as_view(), name="wearable-device-retry-sync"),
    path(
        "native-status/",
        NativeDeviceStatusView.as_view(),
        name="wearable-native-status",
    ),
]

