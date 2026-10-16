from core.utils.serializers import BaseModelSerializer
from integrations.metsights.models import MetsightsProfile


class CustomerMetsightsProfileSerializer(BaseModelSerializer):
    class Meta:
        model = MetsightsProfile
        fields = ["profile_id", "is_active", "created_at", "updated_at"]
        read_only_fields = fields
