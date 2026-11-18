from django.contrib import admin

from wearables.models import (
    HealthDailySummary,
    HealthDomainSnapshot,
    RookOutbox,
    RookMemberIdentity,
    RookWebhookReceipt,
    WearableConnection,
    WearableConnectionEvent,
    WearableConsent,
)

admin.site.register(RookMemberIdentity)
admin.site.register(WearableConsent)
admin.site.register(WearableConnection)
admin.site.register(WearableConnectionEvent)
admin.site.register(RookWebhookReceipt)
admin.site.register(HealthDailySummary)
admin.site.register(HealthDomainSnapshot)
admin.site.register(RookOutbox)
