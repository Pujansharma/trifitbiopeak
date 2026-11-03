import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.centers.models import Center
from accounts.customers.models import (
    Customer,
    CustomerCenterAssignment,
    CustomerProfile,
)
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.users.utils.constants import Gender
from accounts.users.utils.helper import calculate_age
from accounts.utils.constants import UserType
from supplementation.models import (
    Brand,
    ClientConstraint,
    Protocol,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
    Supplement,
    SupplementActiveIngredient,
    SupplementAllergen,
)
from supplementation.serializers import ProtocolCurrentVersionSerializer
from supplementation.utils.constants import (
    AllergenName,
    AllergenPresenceType,
    ConstraintKind,
    DietaryAttribute,
    ProtocolChangeType,
    ProtocolEventAction,
    ProtocolItemFrequency,
    ProtocolItemTiming,
    ProtocolVersionStatus,
    RawMaterialSourceType,
    SupplementForm,
)
from supplementation.utils.version_status import (
    select_listed_protocol_version,
    sweep_protocol_versions,
)
from supplementation.utils.protocols import protocol_version_bucket
from supplementation.views import (
    ProtocolDetailView,
    ProtocolEventListView,
    SupplementationProfileCurrentVersionListView,
    SupplementationProfileDetailView,
    SupplementationProfileEventListView,
    SupplementationProfileListView,
    SupplementationProfileProtocolListView,
    SupplementCreateView,
    SupplementMasterDetailView,
    PlanProtocolListView,
    PlanRoutineView,
    PlanSummaryView,
    PlanSupplementChangeListView,
    ProtocolVersionApproveView,
    ProtocolVersionCancelView,
    ProtocolVersionExtendView,
    ProtocolVersionEventListView,
    ProtocolVersionCreateView,
    ProtocolItemDetailView,
    ProtocolItemReplaceView,
    ProtocolVersionItemListView,
    ProtocolVersionPublishView,
)


def create_staff_user(email: str, account_type: str) -> User:
    user = User.objects.create_user(email=email)
    UserAccount.objects.create(user=user, account_type=account_type)
    return user


class SupplementationSmokeTests(SimpleTestCase):
    def test_constants_export_api_values(self):
        self.assertIn("capsule", SupplementForm.values)
        self.assertIn("whole food", RawMaterialSourceType.values)
        self.assertIn("in_facility", AllergenPresenceType.values)


class SupplementMasterDetailTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "supplement-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "supplement-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "supplement-customer@example.com",
            UserType.CUSTOMER,
        )
        brand = Brand.objects.create(name="Thorne")
        self.supplement = Supplement.objects.create(
            brand=brand,
            product_name="Vitamin D3",
            form=SupplementForm.CAPSULE,
            sku="TD3",
            manufacturer="Thorne",
            raw_material_source_type=RawMaterialSourceType.WHOLE_FOOD,
            pack_quantity_info="60 capsules",
            serving_size="1 capsule",
            serving_container=60,
            market_country_code="US",
            product_url="https://example.com/d3",
            dietary_attributes=[DietaryAttribute.VEGAN],
            is_active=False,
            created_by=self.admin,
        )
        SupplementActiveIngredient.objects.create(
            supplement=self.supplement,
            ingredient_name="Cholecalciferol",
            serving=Decimal(5000),
            unit="IU",
            form="capsule",
            source="lichen",
            position=0,
        )
        SupplementAllergen.objects.create(
            supplement=self.supplement,
            name=AllergenName.FISH,
            presence_type=AllergenPresenceType.CONTAINS,
        )

    def retrieve(self, user, supplement_id):
        request = self.factory.get(f"/supplementation/master/{supplement_id}/")
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementMasterDetailView.as_view()(request, pk=supplement_id)

    def test_admin_receives_full_product_including_inactive(self):
        response = self.retrieve(self.admin, self.supplement.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Supplement retrieved successfully.")
        self.assertEqual(
            response.data["data"],
            {
                "id": str(self.supplement.pk),
                "brand_name": "Thorne",
                "product_name": "Vitamin D3",
                "form": "capsule",
                "sku": "TD3",
                "manufacturer": "Thorne",
                "raw_material_source_type": "whole food",
                "pack_quantity_info": "60 capsules",
                "serving_size": "1 capsule",
                "serving_container": 60,
                "market_country_code": "US",
                "product_url": "https://example.com/d3",
                "dietary_attributes": ["vegan"],
                "is_active": False,
                "active_ingredients": [
                    {
                        "ingredient_name": "Cholecalciferol",
                        "serving": "5000.0000",
                        "unit": "IU",
                        "form": "capsule",
                        "source": "lichen",
                    }
                ],
                "allergen_information": [{"name": "fish", "type": "contains"}],
            },
        )

    def test_associate_can_retrieve(self):
        response = self.retrieve(self.associate, self.supplement.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.retrieve(self.customer, self.supplement.pk)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_product_is_not_found(self):
        response = self.retrieve(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_returns_saved_allergens(self):
        request = self.factory.post(
            "/supplementation/master/new-supplement/",
            {
                "brand_name": "Nordic Naturals",
                "product_name": "Omega-3",
                "form": "capsule",
                "sku": "OM3",
                "manufacturer": "Nordic Naturals",
                "raw_material_source_type": "whole food",
                "pack_quantity_info": "90 capsules",
                "serving_size": "2 capsules",
                "serving_container": 45,
                "market_country_code": "us",
                "active_ingredients": [
                    {
                        "ingredient_name": "EPA",
                        "serving": "500",
                        "unit": "mg",
                    }
                ],
                "allergen_information": [{"name": "fish", "type": "contains"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = SupplementCreateView.as_view()(request)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["data"]["allergen_information"],
            [{"name": "fish", "type": "contains"}],
        )


def create_profile(
    email: str,
    first_name: str,
    last_name: str,
    gender: str | None = None,
    date_of_birth: date | None = None,
    is_active: bool = True,
) -> CustomerProfile:
    user = User.objects.create_user(email=email)
    customer = Customer.objects.create(user=user, contact_email=email)
    return CustomerProfile.objects.create(
        customer=customer,
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        date_of_birth=date_of_birth,
        is_main=True,
        is_active=is_active,
    )


def publish_current_version(
    profile: CustomerProfile,
    *,
    status: str,
    name: str,
    purpose: str,
    starts_on: date | None = None,
    ends_on: date | None = None,
    review_on: date | None = None,
    version_number: int = 1,
    previous_status: str | None = None,
) -> ProtocolVersion:
    protocol = Protocol.objects.create(
        customer_profile=profile,
        name=name,
        purpose=purpose,
    )
    previous = None
    if previous_status is not None:
        previous = ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=version_number - 1,
            status=previous_status,
            starts_on=starts_on,
            ends_on=ends_on,
        )
    version = ProtocolVersion.objects.create(
        protocol=protocol,
        version_number=version_number,
        status=status,
        starts_on=starts_on,
        ends_on=ends_on,
        review_on=review_on,
        supersedes=previous,
    )
    protocol.current_version = version
    protocol.save(update_fields=["current_version", "updated_at"])
    return version


class ProtocolBucketTests(SimpleTestCase):
    def test_scheduled_open_window_is_active(self):
        today = date(2026, 10, 26)
        version = ProtocolVersion(
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on=date(2026, 10, 1),
        )
        self.assertEqual(protocol_version_bucket(version, today), "active")

    def test_future_scheduled_is_coming_up(self):
        today = date(2026, 10, 26)
        version = ProtocolVersion(
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on=date(2026, 11, 1),
        )
        self.assertEqual(protocol_version_bucket(version, today), "coming_up")

    def test_ended_active_is_historical(self):
        today = date(2026, 10, 26)
        version = ProtocolVersion(
            status=ProtocolVersionStatus.ACTIVE,
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 10, 25),
        )
        self.assertEqual(protocol_version_bucket(version, today), "historical")

    def test_draft_is_preparing(self):
        version = ProtocolVersion(status=ProtocolVersionStatus.DRAFT)
        self.assertEqual(
            protocol_version_bucket(version, date(2026, 10, 26)),
            "preparing",
        )

    def test_under_review_is_not_listed(self):
        version = ProtocolVersion(status=ProtocolVersionStatus.UNDER_REVIEW)
        self.assertIsNone(protocol_version_bucket(version, date(2026, 10, 26)))

    def test_approved_is_preparing(self):
        version = ProtocolVersion(status=ProtocolVersionStatus.APPROVED)
        self.assertEqual(
            protocol_version_bucket(version, date(2026, 10, 26)),
            "preparing",
        )


class SupplementationProfileListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user("profile-admin@example.com", UserType.ADMIN)
        self.associate = create_staff_user(
            "profile-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer_user = create_staff_user(
            "profile-customer@example.com",
            UserType.CUSTOMER,
        )
        today = timezone.localdate()
        self.profile = create_profile(
            "ava@example.com",
            "Ava",
            "Shah",
            gender=Gender.FEMALE,
            date_of_birth=date(1990, 6, 15),
        )
        self.empty_profile = create_profile("empty@example.com", "Noah", "Kim")
        self.hidden_profile = create_profile(
            "hidden@example.com",
            "Hidden",
            "Client",
            is_active=False,
        )
        self.active_version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Foundational Health",
            purpose="Close nutritional gaps",
            starts_on=today - timedelta(days=10),
            review_on=today + timedelta(days=80),
            version_number=2,
            previous_status=ProtocolVersionStatus.SUPERSEDED,
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Coming Up",
            purpose="Later",
            starts_on=today + timedelta(days=14),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Ended",
            purpose="Finished",
            starts_on=today - timedelta(days=40),
            ends_on=today - timedelta(days=1),
        )
        self.fish = ClientConstraint.objects.create(
            customer_profile=self.profile,
            kind=ConstraintKind.ALLERGY,
            name="Fish",
        )
        ClientConstraint.objects.create(
            customer_profile=self.profile,
            kind=ConstraintKind.DIETARY,
            name="Dairy",
            is_active=False,
            notes="Avoid whey",
        )

    def list_profiles(self, user, **params):
        request = self.factory.get("/supplementation/profiles/", params)
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileListView.as_view()(request)

    def test_admin_list_shape(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_profiles(self.admin)
        self.assertLessEqual(len(queries), 8)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplementation profiles retrieved successfully.",
        )
        self.assertEqual(response.data["count"], 2)
        rows = {row["customer_profile"]["id"]: row for row in response.data["data"]}
        self.assertNotIn(str(self.hidden_profile.id), rows)
        empty_row = rows[str(self.empty_profile.id)]
        self.assertEqual(empty_row["constraints"], [])
        self.assertIsNone(empty_row["last_updated_on"])
        self.assertIsNone(empty_row["protocols"]["active_protocol"])
        self.assertEqual(empty_row["protocols"]["coming_up_count"], 0)
        self.assertEqual(empty_row["protocols"]["historical_counts"], 0)

        row = rows[str(self.profile.id)]
        self.assertEqual(
            row["customer_profile"],
            {
                "id": str(self.profile.id),
                "name": "Ava Shah",
                "gender": "Female",
                "age": calculate_age(date(1990, 6, 15)),
            },
        )
        self.assertEqual(
            row["constraints"],
            [
                {
                    "id": str(self.profile.supplement_constraints.get(name="Dairy").id),
                    "kind": "dietary",
                    "name": "Dairy",
                    "severity": None,
                    "notes": "Avoid whey",
                    "is_active": False,
                },
                {
                    "id": str(self.fish.id),
                    "kind": "allergy",
                    "name": "Fish",
                    "severity": None,
                    "notes": None,
                    "is_active": True,
                },
            ],
        )
        self.assertEqual(
            row["last_updated_on"],
            timezone.localdate().isoformat(),
        )
        self.assertEqual(
            row["protocols"],
            {
                "active_protocol": {
                    "id": str(self.active_version.protocol_id),
                    "name": "Foundational Health",
                    "purpose": "Close nutritional gaps",
                    "version_id": str(self.active_version.id),
                    "version_number": 2,
                    "status": "active",
                    "starts_on": self.active_version.starts_on.isoformat(),
                    "ends_on": None,
                    "review_on": self.active_version.review_on.isoformat(),
                },
                "coming_up_count": 1,
                "historical_counts": 1,
            },
        )

    def test_associate_can_list(self):
        response = self.list_profiles(self.associate)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_profiles(self.customer_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_search_matches_full_name(self):
        response = self.list_profiles(self.admin, search="Ava Shah")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["data"][0]["customer_profile"]["id"],
            str(self.profile.id),
        )

    def test_center_filters_assigned_profiles(self):
        center = Center.objects.create(name="Indiranagar", code="BLR-SUP")
        other_center = Center.objects.create(name="Whitefield", code="BLR-WF")
        CustomerCenterAssignment.objects.create(
            customer_profile=self.profile,
            center=center,
        )
        matched = self.list_profiles(self.admin, center=str(center.id))
        self.assertEqual(matched.data["count"], 1)
        self.assertEqual(
            matched.data["data"][0]["customer_profile"]["name"],
            "Ava Shah",
        )
        empty = self.list_profiles(self.admin, center=str(other_center.id))
        self.assertEqual(empty.data["count"], 0)

    def test_invalid_center_is_rejected(self):
        response = self.list_profiles(self.admin, center="not-a-uuid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid center.")


class SupplementationProfileDetailTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user("detail-admin@example.com", UserType.ADMIN)
        self.associate = create_staff_user(
            "detail-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer_user = create_staff_user(
            "detail-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "detail-ava@example.com",
            "Ava",
            "Shah",
            gender=Gender.FEMALE,
            date_of_birth=date(1990, 4, 12),
        )
        profile_user = self.profile.customer.user
        profile_user.phone = "+91-9876543210"
        profile_user.save(update_fields=["phone"])
        self.empty_profile = create_profile("detail-empty@example.com", "Noah", "Kim")
        self.hidden_profile = create_profile(
            "detail-hidden@example.com",
            "Hidden",
            "Client",
            is_active=False,
        )
        self.fish = ClientConstraint.objects.create(
            customer_profile=self.profile,
            kind=ConstraintKind.ALLERGY,
            name="Fish",
        )
        ClientConstraint.objects.create(
            customer_profile=self.profile,
            kind=ConstraintKind.DIETARY,
            name="Dairy",
            is_active=False,
            notes="Avoid whey",
        )
        Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        Protocol.objects.create(
            customer_profile=self.profile,
            name="Retired plan",
            purpose="Old gaps",
            is_active=False,
        )

    def retrieve_profile(self, user, profile_id):
        request = self.factory.get(f"/supplementation/profiles/{profile_id}/")
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileDetailView.as_view()(
            request,
            profile_id=profile_id,
        )

    def test_admin_detail_shape(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.retrieve_profile(self.admin, self.profile.id)
        self.assertLessEqual(len(queries), 6)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplementation profile retrieved successfully.",
        )
        data = response.data["data"]
        self.assertEqual(
            data["customer_profile"],
            {
                "id": str(self.profile.id),
                "name": "Ava Shah",
                "contact_email": "detail-ava@example.com",
                "phone": "+91-9876543210",
                "date_of_birth": "1990-04-12",
                "gender": "Female",
            },
        )
        self.assertNotIn("protocols", data)
        self.assertEqual(data["protocol_count"], 2)
        self.assertEqual(
            data["constraints"],
            [
                {
                    "id": str(self.profile.supplement_constraints.get(name="Dairy").id),
                    "kind": "dietary",
                    "name": "Dairy",
                    "severity": None,
                    "notes": "Avoid whey",
                    "is_active": False,
                },
                {
                    "id": str(self.fish.id),
                    "kind": "allergy",
                    "name": "Fish",
                    "severity": None,
                    "notes": None,
                    "is_active": True,
                },
            ],
        )
    def test_empty_profile(self):
        response = self.retrieve_profile(self.admin, self.empty_profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["customer_profile"],
            {
                "id": str(self.empty_profile.id),
                "name": "Noah Kim",
                "contact_email": "detail-empty@example.com",
                "phone": None,
                "date_of_birth": None,
                "gender": None,
            },
        )
        self.assertEqual(response.data["data"]["constraints"], [])
        self.assertNotIn("protocols", response.data["data"])
        self.assertEqual(response.data["data"]["protocol_count"], 0)

    def test_associate_can_retrieve(self):
        response = self.retrieve_profile(self.associate, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.retrieve_profile(self.customer_user, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_profile_is_not_found(self):
        response = self.retrieve_profile(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_profile_is_not_found(self):
        response = self.retrieve_profile(self.admin, self.hidden_profile.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SupplementationProfileEventListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user("event-admin@example.com", UserType.ADMIN)
        self.associate = create_staff_user(
            "event-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer_user = create_staff_user(
            "event-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile("event-ava@example.com", "Ava", "Shah")
        self.hidden_profile = create_profile(
            "event-hidden@example.com",
            "Hidden",
            "Client",
            is_active=False,
        )
        version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Foundational Health",
            purpose="Close nutritional gaps",
            starts_on=timezone.localdate(),
        )
        self.replaced = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=version.protocol,
            protocol_version=version,
            actor=self.admin,
            action=ProtocolEventAction.SUPPLEMENT_REPLACED,
            reason="Vegan diet.",
            client_visible=True,
            client_title="Fish Oil replaced",
            change_type=ProtocolChangeType.REPLACED,
            effective_on=date(2026, 9, 20),
            before={"product_name": "Fish Oil", "strength_amount": "1000"},
            after={"product_name": "Algae Omega-3", "strength_amount": "1000"},
        )
        self.hidden_event = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            action=ProtocolEventAction.VERSION_DRAFTED,
            client_visible=False,
        )
        ProtocolEvent.objects.filter(pk=self.hidden_event.pk).update(
            created_at=timezone.now() - timedelta(days=2),
        )
        self.hidden_event.refresh_from_db()

    def list_events(self, user, profile_id, **params):
        request = self.factory.get(
            f"/supplementation/profiles/{profile_id}/events/",
            params,
        )
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileEventListView.as_view()(
            request,
            profile_id=profile_id,
        )

    def test_admin_list_shape(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_events(self.admin, self.profile.id, limit=1)
        self.assertLessEqual(len(queries), 5)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplementation events retrieved successfully.",
        )
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.replaced.refresh_from_db()
        self.assertEqual(
            response.data["data"],
            [
                {
                    "id": str(self.replaced.id),
                    "action": "supplement_replaced",
                    "reason": "Vegan diet.",
                    "client_visible": True,
                    "client_title": "Fish Oil replaced",
                    "change_type": "replaced",
                    "effective_on": "2026-09-20",
                    "protocol_id": str(self.replaced.protocol_id),
                    "protocol_version_id": str(self.replaced.protocol_version_id),
                    "before": {"product_name": "Fish Oil", "strength_amount": "1000"},
                    "after": {
                        "product_name": "Algae Omega-3",
                        "strength_amount": "1000",
                    },
                    "created_at": timezone.localtime(
                        self.replaced.created_at
                    ).isoformat(),
                }
            ],
        )

    def test_second_page_is_older_and_includes_hidden_events(self):
        response = self.list_events(self.admin, self.profile.id, limit=1, page=2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)
        row = response.data["data"][0]
        self.assertEqual(row["id"], str(self.hidden_event.id))
        self.assertEqual(row["action"], "version_drafted")
        self.assertFalse(row["client_visible"])
        self.assertIsNone(row["protocol_id"])
        self.assertIsNone(row["protocol_version_id"])
        self.assertIsNone(row["reason"])
        self.assertIsNone(row["change_type"])

    def test_action_filter(self):
        response = self.list_events(
            self.admin,
            self.profile.id,
            action="version_drafted",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.hidden_event.id))

    def test_invalid_action_is_rejected(self):
        response = self.list_events(self.admin, self.profile.id, action="nope")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid action.")

    def test_empty_profile(self):
        empty_profile = create_profile("event-empty@example.com", "Noah", "Kim")
        response = self.list_events(self.admin, empty_profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["data"], [])

    def test_associate_can_list(self):
        response = self.list_events(self.associate, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_events(self.customer_user, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_profile_is_not_found(self):
        response = self.list_events(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_profile_is_not_found(self):
        response = self.list_events(self.admin, self.hidden_profile.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProtocolDetailTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile("protocol-client@example.com", "Ava", "Shah")
        today = timezone.localdate()
        self.current = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset and deeper sleep",
            starts_on=today,
            ends_on=today + timedelta(days=90),
            review_on=today + timedelta(days=60),
            version_number=2,
            previous_status=ProtocolVersionStatus.SUPERSEDED,
        )
        self.protocol = self.current.protocol
        self.previous = self.current.supersedes
        self.empty_protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Empty",
            purpose="No versions",
        )

    def retrieve(self, user, protocol_id):
        request = self.factory.get(f"/supplementation/protocols/{protocol_id}/")
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolDetailView.as_view()(request, pk=protocol_id)

    def test_admin_detail_shape(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.retrieve(self.admin, self.protocol.id)
        self.assertLessEqual(len(queries), 4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Protocol retrieved successfully.")
        self.assertEqual(
            response.data["data"],
            {
                "id": str(self.protocol.id),
                "name": "Sleep & Recovery",
                "purpose": "Faster sleep onset and deeper sleep",
                "current_version_id": str(self.current.id),
                "versions": [
                    {
                        "id": str(self.previous.id),
                        "version_number": 1,
                        "status": "superseded",
                        "starts_on": self.previous.starts_on.isoformat(),
                        "ends_on": self.previous.ends_on.isoformat(),
                        "review_on": None,
                        "supplement_count": 0,
                    },
                    {
                        "id": str(self.current.id),
                        "version_number": 2,
                        "status": "active",
                        "starts_on": self.current.starts_on.isoformat(),
                        "ends_on": self.current.ends_on.isoformat(),
                        "review_on": self.current.review_on.isoformat(),
                        "supplement_count": 0,
                    },
                ],
            },
        )

    def test_supplement_count_matches_protocol_items(self):
        first_supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="PROTOCOL-DETAIL-COUNT-1",
        )
        second_supplement = create_supplement(
            self.admin,
            name="Magnesium",
            sku="PROTOCOL-DETAIL-COUNT-2",
        )
        add_protocol_item(self.previous, first_supplement)
        add_protocol_item(self.previous, second_supplement)
        add_protocol_item(self.current, first_supplement)
        with CaptureQueriesContext(connection) as queries:
            response = self.retrieve(self.admin, self.protocol.id)
        self.assertLessEqual(len(queries), 4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [
                version["supplement_count"]
                for version in response.data["data"]["versions"]
            ],
            [2, 1],
        )

    def test_missing_current_version(self):
        response = self.retrieve(self.admin, self.empty_protocol.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"],
            {
                "id": str(self.empty_protocol.id),
                "name": "Empty",
                "purpose": "No versions",
                "current_version_id": None,
                "versions": [],
            },
        )

    def test_associate_can_retrieve(self):
        response = self.retrieve(self.associate, self.protocol.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.retrieve(self.customer, self.protocol.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_protocol_is_not_found(self):
        response = self.retrieve(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SupplementationProfileProtocolListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-list-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-list-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-list-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile("protocol-list-client@example.com", "Ava", "Shah")
        self.hidden_profile = create_profile(
            "protocol-list-hidden@example.com",
            "Noah",
            "Kim",
            is_active=False,
        )
        today = timezone.localdate()
        self.current = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset and deeper sleep",
            starts_on=today,
            ends_on=today + timedelta(days=90),
            review_on=today + timedelta(days=60),
            version_number=2,
            previous_status=ProtocolVersionStatus.SUPERSEDED,
        )
        self.published = self.current.protocol
        self.previous = self.current.supersedes
        self.draft_protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="New Draft",
            purpose="Still being written",
        )
        self.draft = ProtocolVersion.objects.create(
            protocol=self.draft_protocol,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
        )
        self.draft_protocol.current_version = self.draft
        self.draft_protocol.save(update_fields=["current_version", "updated_at"])

    def list_protocols(self, user, profile_id, **params):
        request = self.factory.get(
            f"/supplementation/profiles/{profile_id}/protocols/",
            params,
        )
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileProtocolListView.as_view()(
            request,
            profile_id=profile_id,
        )

    def test_admin_list_includes_draft_and_every_version(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_protocols(self.admin, self.profile.id)
        self.assertLessEqual(len(queries), 6)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Protocols retrieved successfully.")
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["data"],
            [
                {
                    "id": str(self.draft_protocol.id),
                    "name": "New Draft",
                    "purpose": "Still being written",
                    "current_version_id": str(self.draft.id),
                    "versions": [
                        {
                            "id": str(self.draft.id),
                            "version_number": 1,
                            "status": "draft",
                            "starts_on": None,
                            "ends_on": None,
                            "review_on": None,
                            "supplement_count": 0,
                        }
                    ],
                },
                {
                    "id": str(self.published.id),
                    "name": "Sleep & Recovery",
                    "purpose": "Faster sleep onset and deeper sleep",
                    "current_version_id": str(self.current.id),
                    "versions": [
                        {
                            "id": str(self.previous.id),
                            "version_number": 1,
                            "status": "superseded",
                            "starts_on": self.previous.starts_on.isoformat(),
                            "ends_on": self.previous.ends_on.isoformat(),
                            "review_on": None,
                            "supplement_count": 0,
                        },
                        {
                            "id": str(self.current.id),
                            "version_number": 2,
                            "status": "active",
                            "starts_on": self.current.starts_on.isoformat(),
                            "ends_on": self.current.ends_on.isoformat(),
                            "review_on": self.current.review_on.isoformat(),
                            "supplement_count": 0,
                        },
                    ],
                },
            ],
        )

    def test_second_page(self):
        response = self.list_protocols(self.admin, self.profile.id, limit=1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.draft_protocol.id))

    def test_supplement_count_matches_protocol_items(self):
        first_supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="PROFILE-PROTO-COUNT-1",
        )
        second_supplement = create_supplement(
            self.admin,
            name="Magnesium",
            sku="PROFILE-PROTO-COUNT-2",
        )
        add_protocol_item(self.previous, first_supplement)
        add_protocol_item(self.current, first_supplement)
        add_protocol_item(self.current, second_supplement)
        with CaptureQueriesContext(connection) as queries:
            response = self.list_protocols(self.admin, self.profile.id)
        self.assertLessEqual(len(queries), 6)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"][0]["versions"][0]["supplement_count"],
            0,
        )
        published = response.data["data"][1]["versions"]
        self.assertEqual(published[0]["supplement_count"], 1)
        self.assertEqual(published[1]["supplement_count"], 2)

    def test_empty_profile(self):
        empty_profile = create_profile("protocol-list-empty@example.com", "Mia", "Das")
        response = self.list_protocols(self.admin, empty_profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["data"], [])

    def test_associate_can_list(self):
        response = self.list_protocols(self.associate, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_protocols(self.customer, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_profile_is_not_found(self):
        response = self.list_protocols(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_profile_is_not_found(self):
        response = self.list_protocols(self.admin, self.hidden_profile.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProtocolCreateTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-create-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-create-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-create-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-create-client@example.com",
            "Ava",
            "Shah",
        )
        self.other_profile = create_profile(
            "protocol-create-other@example.com",
            "Noah",
            "Kim",
        )
        self.hidden_profile = create_profile(
            "protocol-create-hidden@example.com",
            "Mia",
            "Das",
            is_active=False,
        )
        today = timezone.localdate()
        self.source = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset and deeper sleep",
            starts_on=today,
            ends_on=today + timedelta(days=90),
            review_on=today + timedelta(days=60),
        )
        self.source.summary_notes = "Cloned later"
        self.source.notes = "Staff note"
        self.source.is_ongoing = True
        self.source.save(
            update_fields=["summary_notes", "notes", "is_ongoing", "updated_at"]
        )
        self.other_source = publish_current_version(
            self.other_profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Other Protocol",
            purpose="Belongs to someone else",
            starts_on=today,
        )

    def create_protocol(self, user, profile_id, payload):
        request = self.factory.post(
            f"/supplementation/profiles/{profile_id}/protocols/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileProtocolListView.as_view()(
            request,
            profile_id=profile_id,
        )

    def test_scratch_creates_draft_version(self):
        response = self.create_protocol(
            self.admin,
            self.profile.id,
            {
                "name": "Foundational Health",
                "purpose": "Close nutritional gaps from your blood panel",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["detail"], "Protocol created.")
        protocol = Protocol.objects.get(pk=response.data["data"]["id"])
        version = protocol.versions.get()
        self.assertEqual(protocol.customer_profile_id, self.profile.id)
        self.assertIsNone(protocol.current_version_id)
        self.assertEqual(protocol.created_by_id, self.admin.id)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.status, ProtocolVersionStatus.DRAFT)
        self.assertEqual(protocol.name, "Foundational Health")
        self.assertEqual(
            protocol.purpose,
            "Close nutritional gaps from your blood panel",
        )
        self.assertEqual(version.notes, "")
        self.assertIsNone(version.summary_notes)
        self.assertFalse(version.is_ongoing)
        self.assertIsNone(version.starts_on)
        self.assertEqual(
            response.data["data"],
            {
                "id": str(protocol.id),
                "name": "Foundational Health",
                "purpose": "Close nutritional gaps from your blood panel",
                "current_version_id": None,
                "versions": [
                    {
                        "id": str(version.id),
                        "version_number": 1,
                        "status": "draft",
                        "starts_on": None,
                        "ends_on": None,
                        "review_on": None,
                        "supplement_count": 0,
                    }
                ],
            },
        )
        events = list(
            ProtocolEvent.objects.filter(protocol=protocol).order_by("created_at", "id")
        )
        self.assertEqual(
            [event.action for event in events],
            [
                ProtocolEventAction.PROTOCOL_CREATED,
                ProtocolEventAction.VERSION_DRAFTED,
            ],
        )
        self.assertTrue(all(event.client_visible is False for event in events))
        self.assertTrue(all(event.actor_id == self.admin.id for event in events))
        self.assertEqual(
            events[1].after,
            {"version_number": 1, "status": "draft"},
        )

    def test_copy_starts_a_new_protocol(self):
        response = self.create_protocol(
            self.associate,
            self.profile.id,
            {"source_version_id": str(self.source.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        protocol = Protocol.objects.get(pk=response.data["data"]["id"])
        version = protocol.versions.get()
        self.assertNotEqual(protocol.id, self.source.protocol_id)
        self.assertIsNone(protocol.current_version_id)
        self.assertEqual(protocol.created_by_id, self.associate.id)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.status, ProtocolVersionStatus.DRAFT)
        self.assertEqual(protocol.name, "Sleep & Recovery")
        self.assertEqual(protocol.purpose, "Faster sleep onset and deeper sleep")
        self.assertEqual(version.notes, "Staff note")
        self.assertEqual(version.summary_notes, "Cloned later")
        self.assertTrue(version.is_ongoing)
        self.assertIsNone(version.starts_on)
        self.assertIsNone(version.ends_on)
        self.assertIsNone(version.review_on)
        drafted = ProtocolEvent.objects.get(
            protocol=protocol,
            action=ProtocolEventAction.VERSION_DRAFTED,
        )
        self.assertEqual(
            drafted.after["source_version_id"],
            str(self.source.id),
        )

    def test_copy_overrides_name_and_purpose(self):
        response = self.create_protocol(
            self.admin,
            self.profile.id,
            {
                "source_version_id": str(self.source.id),
                "name": "Sleep copy",
                "purpose": "Shorter wind-down",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        protocol = Protocol.objects.get(pk=response.data["data"]["id"])
        version = protocol.versions.get()
        self.assertEqual(protocol.name, "Sleep copy")
        self.assertEqual(protocol.purpose, "Shorter wind-down")
        self.assertEqual(version.notes, "")
        self.assertEqual(version.summary_notes, "Cloned later")

    def test_scratch_requires_name_and_purpose(self):
        response = self.create_protocol(self.admin, self.profile.id, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            {
                "name": ["This field is required."],
                "purpose": ["This field is required."],
            },
        )

    def test_source_on_another_profile_is_not_found(self):
        response = self.create_protocol(
            self.admin,
            self.profile.id,
            {"source_version_id": str(self.other_source.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")

    def test_unknown_source_is_not_found(self):
        response = self.create_protocol(
            self.admin,
            self.profile.id,
            {"source_version_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_is_forbidden(self):
        response = self.create_protocol(
            self.customer,
            self.profile.id,
            {"name": "Sleep", "purpose": "Rest"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_profile_is_not_found(self):
        response = self.create_protocol(
            self.admin,
            self.hidden_profile.id,
            {"name": "Sleep", "purpose": "Rest"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ListedProtocolVersionTests(SimpleTestCase):
    def test_highest_published_status_wins_over_an_older_superseded_version(self):
        selected = select_listed_protocol_version(
            [
                ProtocolVersion(
                    version_number=1,
                    status=ProtocolVersionStatus.SUPERSEDED,
                ),
                ProtocolVersion(
                    version_number=2,
                    status=ProtocolVersionStatus.ACTIVE,
                ),
                ProtocolVersion(
                    version_number=3,
                    status=ProtocolVersionStatus.DRAFT,
                ),
            ]
        )
        self.assertEqual(selected.version_number, 2)
        self.assertEqual(selected.status, ProtocolVersionStatus.ACTIVE)

    def test_superseded_version_is_listed_when_every_newer_version_is_unfinished(self):
        selected = select_listed_protocol_version(
            [
                ProtocolVersion(
                    version_number=1,
                    status=ProtocolVersionStatus.SUPERSEDED,
                ),
                ProtocolVersion(
                    version_number=2,
                    status=ProtocolVersionStatus.UNDER_REVIEW,
                ),
            ]
        )
        self.assertEqual(selected.version_number, 1)
        self.assertEqual(selected.status, ProtocolVersionStatus.SUPERSEDED)

    def test_approved_scheduled_expired_and_cancelled_are_listed(self):
        for status_value in (
            ProtocolVersionStatus.APPROVED,
            ProtocolVersionStatus.SCHEDULED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        ):
            with self.subTest(status_value=status_value):
                selected = select_listed_protocol_version(
                    [
                        ProtocolVersion(version_number=1, status=status_value),
                    ]
                )
                self.assertEqual(selected.status, status_value)

    def test_draft_and_bare_superseded_versions_are_omitted(self):
        self.assertIsNone(
            select_listed_protocol_version(
                [
                    ProtocolVersion(
                        version_number=1,
                        status=ProtocolVersionStatus.DRAFT,
                    ),
                ]
            )
        )
        self.assertIsNone(
            select_listed_protocol_version(
                [
                    ProtocolVersion(
                        version_number=1,
                        status=ProtocolVersionStatus.SUPERSEDED,
                    ),
                ]
            )
        )


class SupplementationProfileCurrentVersionListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "current-version-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "current-version-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "current-version-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "current-version-client@example.com",
            "Ava",
            "Shah",
        )
        self.hidden_profile = create_profile(
            "current-version-hidden@example.com",
            "Noah",
            "Kim",
            is_active=False,
        )
        today = timezone.localdate()
        self.older = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Coming Later",
            purpose="Not started",
            starts_on=today + timedelta(days=14),
        )
        self.newer = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            starts_on=today,
            version_number=2,
            previous_status=ProtocolVersionStatus.SUPERSEDED,
        )
        self.unpublished = Protocol.objects.create(
            customer_profile=self.profile,
            name="Unpublished",
            purpose="No current version",
        )
        ProtocolVersion.objects.create(
            protocol=self.unpublished,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
        )
        self.inactive_version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Retired",
            purpose="Hidden protocol",
            starts_on=today,
        )
        self.inactive_version.protocol.is_active = False
        self.inactive_version.protocol.save(update_fields=["is_active", "updated_at"])

    def list_current_versions(self, user, profile_id):
        request = self.factory.get(
            f"/supplementation/profiles/{profile_id}/protocols/current-versions/",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return SupplementationProfileCurrentVersionListView.as_view()(
            request,
            profile_id=profile_id,
        )

    def test_admin_list_shape(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_current_versions(self.admin, self.profile.id)
        self.assertLessEqual(len(queries), 4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Current protocol versions retrieved successfully.",
        )
        self.assertNotIn("count", response.data)
        self.assertEqual(
            [row["id"] for row in response.data["data"]],
            [
                str(self.inactive_version.protocol_id),
                str(self.newer.protocol_id),
                str(self.older.protocol_id),
            ],
        )
        self.assertEqual(
            [row["status"] for row in response.data["data"]],
            [
                ProtocolVersionStatus.ACTIVE,
                ProtocolVersionStatus.ACTIVE,
                ProtocolVersionStatus.SCHEDULED,
            ],
        )
        self.assertEqual(
            response.data["data"][1]["current_version_id"],
            str(self.newer.id),
        )
        self.assertTrue(
            all(row["supplement_count"] == 0 for row in response.data["data"])
        )

    def test_versions_with_supplements_are_listed(self):
        first_supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="CURRENT-VER-COUNT-1",
        )
        second_supplement = create_supplement(
            self.admin,
            name="Magnesium",
            sku="CURRENT-VER-COUNT-2",
        )
        add_protocol_item(self.newer, first_supplement)
        add_protocol_item(self.newer, second_supplement)
        with CaptureQueriesContext(connection) as queries:
            response = self.list_current_versions(self.admin, self.profile.id)
        self.assertLessEqual(len(queries), 4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["id"] for row in response.data["data"]],
            [
                str(self.inactive_version.protocol_id),
                str(self.newer.protocol_id),
                str(self.older.protocol_id),
            ],
        )
        self.assertEqual(
            [row["supplement_count"] for row in response.data["data"]],
            [0, 2, 0],
        )

    def test_row_shape(self):
        protocol = Protocol.objects.select_related("current_version").get(
            pk=self.newer.protocol_id,
        )
        self.assertEqual(
            ProtocolCurrentVersionSerializer(protocol).data,
            {
                "id": str(protocol.id),
                "current_version_id": str(self.newer.id),
                "version_name": "v2",
                "supplement_count": 0,
                "effective_from": self.newer.starts_on.isoformat(),
                "status": "active",
            },
        )

    def test_approved_version_is_listed_before_publish(self):
        protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Approved only",
            purpose="Waiting to publish",
        )
        version = ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=1,
            status=ProtocolVersionStatus.APPROVED,
            starts_on=timezone.localdate(),
        )
        response = self.list_current_versions(self.admin, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(protocol.current_version_id)
        self.assertEqual(
            response.data["data"][0],
            {
                "id": str(protocol.id),
                "current_version_id": str(version.id),
                "version_name": "v1",
                "supplement_count": 0,
                "effective_from": version.starts_on.isoformat(),
                "status": ProtocolVersionStatus.APPROVED,
            },
        )

    def test_superseded_version_is_listed_when_newer_version_is_draft(self):
        protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Replaced then redrafted",
            purpose="Copy the last published version",
        )
        superseded = ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=1,
            status=ProtocolVersionStatus.SUPERSEDED,
            starts_on=timezone.localdate(),
        )
        ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=2,
            status=ProtocolVersionStatus.DRAFT,
        )
        response = self.list_current_versions(self.admin, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"][0]["id"], str(protocol.id))
        self.assertEqual(
            response.data["data"][0]["current_version_id"],
            str(superseded.id),
        )
        self.assertEqual(
            response.data["data"][0]["status"],
            ProtocolVersionStatus.SUPERSEDED,
        )
        self.assertEqual(response.data["data"][0]["version_name"], "v1")

    def test_empty_profile(self):
        empty_profile = create_profile(
            "current-version-empty@example.com",
            "Mia",
            "Das",
        )
        response = self.list_current_versions(self.admin, empty_profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], [])

    def test_associate_can_list(self):
        response = self.list_current_versions(self.associate, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_current_versions(self.customer, self.profile.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_profile_is_not_found(self):
        response = self.list_current_versions(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_profile_is_not_found(self):
        response = self.list_current_versions(self.admin, self.hidden_profile.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProtocolEventListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-event-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-event-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-event-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-event-client@example.com",
            "Ava",
            "Shah",
        )
        today = timezone.localdate()
        self.version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            starts_on=today,
        )
        self.other_version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Other",
            purpose="Different protocol",
            starts_on=today,
        )
        self.replaced = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            protocol_version=self.version,
            actor=self.admin,
            action=ProtocolEventAction.SUPPLEMENT_REPLACED,
            reason="Vegan diet.",
            client_visible=True,
            client_title="Fish Oil replaced",
            change_type=ProtocolChangeType.REPLACED,
            effective_on=date(2026, 9, 20),
            before={"product_name": "Fish Oil", "strength_amount": "1000"},
            after={"product_name": "Algae Omega-3", "strength_amount": "1000"},
        )
        self.older = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            protocol_version=self.version,
            action=ProtocolEventAction.VERSION_DRAFTED,
            client_visible=False,
        )
        ProtocolEvent.objects.filter(pk=self.older.pk).update(
            created_at=timezone.now() - timedelta(days=2),
        )
        self.older.refresh_from_db()
        ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.other_version.protocol,
            action=ProtocolEventAction.PROTOCOL_CREATED,
        )
        ProtocolEvent.objects.create(
            customer_profile=self.profile,
            action=ProtocolEventAction.CONSTRAINT_ADDED,
        )
        self.inactive_version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Retired",
            purpose="Hidden protocol",
            starts_on=today,
        )
        self.inactive_version.protocol.is_active = False
        self.inactive_version.protocol.save(update_fields=["is_active", "updated_at"])
        self.inactive_event = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.inactive_version.protocol,
            action=ProtocolEventAction.PROTOCOL_CREATED,
            client_visible=False,
        )

    def list_events(self, user, protocol_id, **params):
        request = self.factory.get(
            f"/supplementation/protocols/{protocol_id}/events/",
            params,
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolEventListView.as_view()(request, pk=protocol_id)

    def test_admin_list_is_protocol_subset(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_events(self.admin, self.version.protocol_id, limit=1)
        self.assertLessEqual(len(queries), 5)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Protocol events retrieved successfully.",
        )
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.replaced.refresh_from_db()
        self.assertEqual(
            response.data["data"],
            [
                {
                    "id": str(self.replaced.id),
                    "action": "supplement_replaced",
                    "reason": "Vegan diet.",
                    "client_visible": True,
                    "client_title": "Fish Oil replaced",
                    "change_type": "replaced",
                    "effective_on": "2026-09-20",
                    "protocol_id": str(self.version.protocol_id),
                    "protocol_version_id": str(self.version.id),
                    "before": {"product_name": "Fish Oil", "strength_amount": "1000"},
                    "after": {
                        "product_name": "Algae Omega-3",
                        "strength_amount": "1000",
                    },
                    "created_at": timezone.localtime(
                        self.replaced.created_at
                    ).isoformat(),
                }
            ],
        )

    def test_second_page_includes_hidden_events(self):
        response = self.list_events(
            self.admin,
            self.version.protocol_id,
            limit=1,
            page=2,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"][0]["id"], str(self.older.id))
        self.assertFalse(response.data["data"][0]["client_visible"])

    def test_action_filter(self):
        response = self.list_events(
            self.admin,
            self.version.protocol_id,
            action="version_drafted",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.older.id))

    def test_invalid_action_is_rejected(self):
        response = self.list_events(
            self.admin,
            self.version.protocol_id,
            action="nope",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid action.")

    def test_empty_protocol(self):
        empty = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Empty",
            purpose="No events",
        )
        response = self.list_events(self.admin, empty.protocol_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["data"], [])

    def test_inactive_protocol_still_loads(self):
        response = self.list_events(self.admin, self.inactive_version.protocol_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.inactive_event.id))

    def test_associate_can_list(self):
        response = self.list_events(self.associate, self.version.protocol_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_events(self.customer, self.version.protocol_id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_protocol_is_not_found(self):
        response = self.list_events(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProtocolVersionEventListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "version-event-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "version-event-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "version-event-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "version-event-client@example.com",
            "Ava",
            "Shah",
        )
        today = timezone.localdate()
        self.version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset",
            starts_on=today,
        )
        self.sibling = ProtocolVersion.objects.create(
            protocol=self.version.protocol,
            version_number=2,
            status=ProtocolVersionStatus.DRAFT,
        )
        self.replaced = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            protocol_version=self.version,
            actor=self.admin,
            action=ProtocolEventAction.SUPPLEMENT_REPLACED,
            reason="Vegan diet.",
            client_visible=True,
            client_title="Fish Oil replaced",
            change_type=ProtocolChangeType.REPLACED,
            effective_on=date(2026, 9, 20),
            before={"product_name": "Fish Oil", "strength_amount": "1000"},
            after={"product_name": "Algae Omega-3", "strength_amount": "1000"},
        )
        self.older = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            protocol_version=self.version,
            action=ProtocolEventAction.VERSION_DRAFTED,
            client_visible=False,
        )
        ProtocolEvent.objects.filter(pk=self.older.pk).update(
            created_at=timezone.now() - timedelta(days=2),
        )
        self.older.refresh_from_db()
        ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            protocol_version=self.sibling,
            action=ProtocolEventAction.VERSION_DRAFTED,
        )
        ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.version.protocol,
            action=ProtocolEventAction.PROTOCOL_RENAMED,
        )
        self.inactive_version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Hidden",
            purpose="Inactive protocol",
            starts_on=today,
        )
        self.inactive_version.protocol.is_active = False
        self.inactive_version.protocol.save(update_fields=["is_active", "updated_at"])
        self.inactive_event = ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.inactive_version.protocol,
            protocol_version=self.inactive_version,
            action=ProtocolEventAction.PROTOCOL_CREATED,
            client_visible=False,
        )

    def list_events(self, user, version_id, **params):
        request = self.factory.get(
            f"/supplementation/protocol-versions/{version_id}/events/",
            params,
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionEventListView.as_view()(request, pk=version_id)

    def test_admin_list_is_version_subset(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.list_events(self.admin, self.version.id, limit=1)
        self.assertLessEqual(len(queries), 5)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Protocol version events retrieved successfully.",
        )
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.replaced.refresh_from_db()
        self.assertEqual(
            response.data["data"],
            [
                {
                    "id": str(self.replaced.id),
                    "action": "supplement_replaced",
                    "reason": "Vegan diet.",
                    "client_visible": True,
                    "client_title": "Fish Oil replaced",
                    "change_type": "replaced",
                    "effective_on": "2026-09-20",
                    "protocol_id": str(self.version.protocol_id),
                    "protocol_version_id": str(self.version.id),
                    "before": {"product_name": "Fish Oil", "strength_amount": "1000"},
                    "after": {
                        "product_name": "Algae Omega-3",
                        "strength_amount": "1000",
                    },
                    "created_at": timezone.localtime(
                        self.replaced.created_at
                    ).isoformat(),
                }
            ],
        )

    def test_second_page_includes_hidden_events(self):
        response = self.list_events(self.admin, self.version.id, limit=1, page=2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"][0]["id"], str(self.older.id))
        self.assertFalse(response.data["data"][0]["client_visible"])

    def test_action_filter(self):
        response = self.list_events(
            self.admin,
            self.version.id,
            action="version_drafted",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.older.id))

    def test_invalid_action_is_rejected(self):
        response = self.list_events(self.admin, self.version.id, action="nope")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid action.")

    def test_empty_version(self):
        empty = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Empty",
            purpose="No events",
        )
        response = self.list_events(self.admin, empty.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["data"], [])

    def test_inactive_protocol_still_loads(self):
        response = self.list_events(self.admin, self.inactive_version.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.inactive_event.id))

    def test_associate_can_list(self):
        response = self.list_events(self.associate, self.version.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_is_forbidden(self):
        response = self.list_events(self.customer, self.version.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        response = self.list_events(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")


def create_supplement(actor, *, name, sku, is_active=True) -> Supplement:
    brand = Brand.objects.create(name=f"Brand {sku}")
    return Supplement.objects.create(
        brand=brand,
        product_name=name,
        form=SupplementForm.CAPSULE,
        sku=sku,
        manufacturer="Biopeak",
        raw_material_source_type=RawMaterialSourceType.NATURAL,
        pack_quantity_info="60 capsules",
        serving_size="1 capsule",
        serving_container=60,
        market_country_code="IN",
        is_active=is_active,
        created_by=actor,
    )


class ProtocolItemTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-item-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-item-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-item-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-item-client@example.com",
            "Ava",
            "Shah",
        )
        self.version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="ITEM-D3",
        )

    def item_payload(self, **overrides):
        payload = {
            "version_id": str(self.version.id),
            "supplement_id": str(self.supplement.id),
            "dosage": "1 capsule",
            "frequency": ProtocolItemFrequency.DAILY,
            "custom_frequency": None,
            "timing": ProtocolItemTiming.WITH_BREAKFAST,
            "duration": "30 days",
            "instructions": "Take 1 capsule with your morning meal.",
            "rationale": "25(OH)D was 32 ng/mL.",
        }
        payload.update(overrides)
        return payload

    def add_item(self, user, version_id, payload):
        request = self.factory.post(
            f"/supplementation/protocol-versions/{version_id}/items/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionItemListView.as_view()(request, pk=version_id)

    def list_items(self, user, version_id):
        request = self.factory.get(
            f"/supplementation/protocol-versions/{version_id}/items/",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionItemListView.as_view()(request, pk=version_id)

    def test_admin_adds_supplement_to_draft(self):
        response = self.add_item(self.admin, self.version.id, self.item_payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["detail"],
            "Supplement added to protocol version.",
        )
        item = ProtocolItem.objects.get(version=self.version)
        self.assertEqual(
            response.data["data"],
            {
                "id": str(item.id),
                "version_id": str(self.version.id),
                "supplement": {
                    "id": str(self.supplement.id),
                    "product_name": "Vitamin D3",
                    "brand_name": "Brand ITEM-D3",
                    "form": "capsule",
                },
                "dosage": "1 capsule",
                "frequency": "daily",
                "custom_frequency": None,
                "timing": ProtocolItemTiming.WITH_BREAKFAST,
                "duration": "30 days",
                "instructions": "Take 1 capsule with your morning meal.",
                "rationale": "25(OH)D was 32 ng/mL.",
            },
        )
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.SUPPLEMENT_ADDED)
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(event.after["frequency"], "daily")
        self.assertIsNone(event.after["custom_frequency"])

    def test_custom_frequency_is_stored(self):
        response = self.add_item(
            self.associate,
            self.version.id,
            self.item_payload(
                frequency=ProtocolItemFrequency.CUSTOM,
                custom_frequency="Every 3 days",
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["frequency"], "custom")
        self.assertEqual(response.data["data"]["custom_frequency"], "Every 3 days")

    def test_custom_frequency_required_when_frequency_is_custom(self):
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(frequency=ProtocolItemFrequency.CUSTOM),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_frequency", response.data["detail"])

    def test_custom_frequency_rejected_unless_custom(self):
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(custom_frequency="Every 3 days"),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_frequency", response.data["detail"])

    def test_timing_must_be_a_known_value(self):
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(timing="With breakfast"),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("timing", response.data["detail"])

    def test_non_draft_version_rejects_add(self):
        active = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Live",
            purpose="Already published",
            starts_on=timezone.localdate(),
        )
        response = self.add_item(
            self.admin,
            active.id,
            self.item_payload(version_id=str(active.id)),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("version_id", response.data["detail"])

    def test_version_id_must_match_the_path(self):
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(version_id=str(uuid.uuid4())),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("version_id", response.data["detail"])

    def test_unknown_supplement_is_not_found(self):
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(supplement_id=str(uuid.uuid4())),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Supplement not found.")

    def test_inactive_supplement_is_rejected(self):
        inactive = create_supplement(
            self.admin,
            name="Old Fish Oil",
            sku="ITEM-FISH",
            is_active=False,
        )
        response = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(supplement_id=str(inactive.id)),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supplement_id", response.data["detail"])

    def test_same_supplement_cannot_be_added_twice(self):
        first = self.add_item(self.admin, self.version.id, self.item_payload())
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.add_item(self.admin, self.version.id, self.item_payload())
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            second.data["detail"]["supplement_id"],
            ["This supplement is already on this version."],
        )
        self.assertEqual(ProtocolItem.objects.filter(version=self.version).count(), 1)
        self.assertEqual(
            ProtocolEvent.objects.filter(
                protocol_version=self.version,
                action=ProtocolEventAction.SUPPLEMENT_ADDED,
            ).count(),
            1,
        )

    def test_same_supplement_can_be_added_to_another_version(self):
        self.add_item(self.admin, self.version.id, self.item_payload())
        other = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Metabolic",
            purpose="Second plan",
        )
        response = self.add_item(
            self.admin,
            other.id,
            self.item_payload(version_id=str(other.id)),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ProtocolItem.objects.filter(version=other).count(), 1)

    def test_list_returns_added_supplements_oldest_first(self):
        first = self.add_item(self.admin, self.version.id, self.item_payload())
        second_supplement = create_supplement(
            self.admin,
            name="Magnesium",
            sku="ITEM-MAG",
        )
        second = self.add_item(
            self.admin,
            self.version.id,
            self.item_payload(
                supplement_id=str(second_supplement.id),
                dosage="2 capsules",
                frequency=ProtocolItemFrequency.TWICE_DAILY,
                timing=ProtocolItemTiming.AFTER_DINNER,
                duration="ongoing",
            ),
        )
        response = self.list_items(self.associate, self.version.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Protocol supplements retrieved.")
        self.assertNotIn("count", response.data)
        self.assertEqual(
            [row["id"] for row in response.data["data"]],
            [first.data["data"]["id"], second.data["data"]["id"]],
        )

    def test_empty_version_lists_no_supplements(self):
        response = self.list_items(self.admin, self.version.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], [])

    def test_customer_is_forbidden(self):
        response = self.list_items(self.customer, self.version.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        missing = uuid.uuid4()
        response = self.list_items(self.admin, missing)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")


class ProtocolItemChangeTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-item-change-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-item-change-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-item-change-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-item-change-client@example.com",
            "Ava",
            "Shah",
        )
        self.version = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="CHANGE-D3",
        )
        self.replacement = create_supplement(
            self.admin,
            name="Algae Omega-3",
            sku="CHANGE-ALGAE",
        )
        self.item = add_protocol_item(self.version, self.supplement)

    def edit_payload(self, **overrides):
        payload = {
            "dosage": "2 capsules",
            "frequency": ProtocolItemFrequency.DAILY,
            "custom_frequency": None,
            "timing": ProtocolItemTiming.WITH_LUNCH,
            "duration": "60 days",
            "instructions": "Take 2 capsules with lunch.",
            "reason": "Dose raised after the repeat panel.",
        }
        payload.update(overrides)
        return payload

    def replace_payload(self, **overrides):
        payload = {
            "version_id": str(self.item.version.pk),
            "supplement_id": str(self.replacement.id),
            "dosage": "2 softgels",
            "frequency": ProtocolItemFrequency.DAILY,
            "custom_frequency": None,
            "timing": ProtocolItemTiming.WITH_LUNCH,
            "duration": "90 days",
            "instructions": "Take 2 softgels with your largest meal.",
            "rationale": "Cardiovascular support.",
        }
        payload.update(overrides)
        return payload

    def item_row(self, item):
        return {
            "id": str(item.id),
            "version_id": str(item.version.pk),
            "supplement": {
                "id": str(item.supplement.pk),
                "product_name": item.supplement.product_name,
                "brand_name": item.supplement.brand.name,
                "form": item.supplement.form,
            },
            "dosage": item.dosage,
            "frequency": item.frequency,
            "custom_frequency": item.custom_frequency,
            "timing": item.timing,
            "duration": item.duration,
            "instructions": item.instructions,
            "rationale": item.rationale,
        }

    def edit_item(self, user, item_id, payload):
        request = self.factory.patch(
            f"/supplementation/protocol-items/{item_id}/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolItemDetailView.as_view()(request, pk=item_id)

    def replace_item(self, user, item_id, payload):
        request = self.factory.post(
            f"/supplementation/protocol-items/{item_id}/replace/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolItemReplaceView.as_view()(request, pk=item_id)

    def delete_item(self, user, item_id, payload):
        request = self.factory.delete(
            f"/supplementation/protocol-items/{item_id}/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolItemDetailView.as_view()(request, pk=item_id)

    def test_admin_edits_draft_item(self):
        response = self.edit_item(self.admin, self.item.id, self.edit_payload())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplement updated on protocol version.",
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.dosage, "2 capsules")
        self.assertEqual(self.item.supplement.pk, self.supplement.pk)
        self.assertEqual(self.item.rationale, "Low vitamin D.")
        self.assertEqual(response.data["data"], self.item_row(self.item))
        self.assertNotIn("reason", response.data["data"])
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.SUPPLEMENT_MODIFIED)
        self.assertEqual(event.reason, "Dose raised after the repeat panel.")
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(event.before["dosage"], "1 capsule")
        self.assertEqual(event.after["dosage"], "2 capsules")
        self.assertEqual(event.before["supplement_id"], str(self.supplement.id))
        self.assertEqual(event.after["rationale"], "Low vitamin D.")

    def test_associate_edits_under_review_item(self):
        self.version.status = ProtocolVersionStatus.UNDER_REVIEW
        self.version.save(update_fields=["status", "updated_at"])
        response = self.edit_item(
            self.associate,
            self.item.id,
            self.edit_payload(
                frequency=ProtocolItemFrequency.CUSTOM,
                custom_frequency="Every 3 days",
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.frequency, ProtocolItemFrequency.CUSTOM)
        self.assertEqual(self.item.custom_frequency, "Every 3 days")
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.UNDER_REVIEW)

    def test_edit_custom_frequency_rules(self):
        missing = self.edit_item(
            self.admin,
            self.item.id,
            self.edit_payload(frequency=ProtocolItemFrequency.CUSTOM),
        )
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_frequency", missing.data["detail"])
        rejected = self.edit_item(
            self.admin,
            self.item.id,
            self.edit_payload(custom_frequency="Every 3 days"),
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_frequency", rejected.data["detail"])

    def test_associate_replaces_draft_item(self):
        response = self.replace_item(
            self.associate,
            self.item.id,
            self.replace_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplement replaced on protocol version.",
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplement.pk, self.replacement.pk)
        self.assertEqual(self.item.dosage, "2 softgels")
        self.assertEqual(self.item.rationale, "Cardiovascular support.")
        self.assertEqual(response.data["data"], self.item_row(self.item))
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.SUPPLEMENT_REPLACED)
        self.assertIsNone(event.reason)
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.associate.pk)
        self.assertEqual(event.before["supplement_id"], str(self.supplement.id))
        self.assertEqual(event.after["supplement_id"], str(self.replacement.id))
        self.assertEqual(ProtocolItem.objects.filter(version=self.version).count(), 1)

    def test_event_lists_return_supplement_name(self):
        self.replace_item(self.associate, self.item.id, self.replace_payload())
        protocol_request = self.factory.get(
            f"/supplementation/protocols/{self.version.protocol_id}/events/",
        )
        force_authenticate(protocol_request, user=self.admin)
        protocol_response = ProtocolEventListView.as_view()(
            protocol_request,
            pk=self.version.protocol_id,
        )
        version_request = self.factory.get(
            f"/supplementation/protocol-versions/{self.version.id}/events/",
        )
        force_authenticate(version_request, user=self.admin)
        version_response = ProtocolVersionEventListView.as_view()(
            version_request,
            pk=self.version.id,
        )
        for response in (protocol_response, version_response):
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            row = response.data["data"][0]
            self.assertEqual(
                row["before"]["supplement"],
                {
                    "id": str(self.supplement.id),
                    "product_name": "Vitamin D3",
                    "brand_name": "Brand CHANGE-D3",
                    "form": "capsule",
                },
            )
            self.assertEqual(
                row["after"]["supplement"],
                {
                    "id": str(self.replacement.id),
                    "product_name": "Algae Omega-3",
                    "brand_name": "Brand CHANGE-ALGAE",
                    "form": "capsule",
                },
            )
            self.assertNotIn("supplement_id", row["before"])
            self.assertNotIn("supplement_id", row["after"])
            self.assertEqual(row["before"]["dosage"], "1 capsule")
        stored = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(stored.before["supplement_id"], str(self.supplement.id))
        self.assertNotIn("supplement", stored.before)

    def test_admin_replaces_under_review_item(self):
        self.version.status = ProtocolVersionStatus.UNDER_REVIEW
        self.version.save(update_fields=["status", "updated_at"])
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplement.pk, self.replacement.pk)

    def test_replace_version_id_must_match_the_item(self):
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(version_id=str(uuid.uuid4())),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("version_id", response.data["detail"])
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplement.pk, self.supplement.pk)

    def test_replace_unknown_supplement_is_not_found(self):
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(supplement_id=str(uuid.uuid4())),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Supplement not found.")

    def test_replace_inactive_supplement_is_rejected(self):
        inactive = create_supplement(
            self.admin,
            name="Old Fish Oil",
            sku="CHANGE-FISH",
            is_active=False,
        )
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(supplement_id=str(inactive.id)),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("supplement_id", response.data["detail"])

    def test_replace_rejects_a_supplement_already_on_the_version(self):
        other = add_protocol_item(self.version, self.replacement)
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"]["supplement_id"],
            ["This supplement is already on this version."],
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplement.pk, self.supplement.pk)
        other.refresh_from_db()
        self.assertEqual(other.supplement.pk, self.replacement.pk)
        self.assertFalse(
            ProtocolEvent.objects.filter(
                protocol_version=self.version,
                action=ProtocolEventAction.SUPPLEMENT_REPLACED,
            ).exists()
        )

    def test_replace_can_keep_the_same_supplement(self):
        response = self.replace_item(
            self.admin,
            self.item.id,
            self.replace_payload(supplement_id=str(self.supplement.id)),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplement.pk, self.supplement.pk)
        self.assertEqual(ProtocolItem.objects.filter(version=self.version).count(), 1)

    def test_admin_deletes_draft_item(self):
        response = self.delete_item(
            self.admin,
            self.item.id,
            {"reason": "Levels normalized on blood panel"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {"detail": "Supplement removed from protocol version."},
        )
        self.assertFalse(ProtocolItem.objects.filter(pk=self.item.id).exists())
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.SUPPLEMENT_REMOVED)
        self.assertEqual(event.reason, "Levels normalized on blood panel")
        self.assertIsNone(event.client_reason)
        self.assertIsNone(event.after)
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(event.before["supplement_id"], str(self.supplement.id))
        self.assertEqual(event.before["dosage"], "1 capsule")

    def test_associate_deletes_under_review_item(self):
        self.version.status = ProtocolVersionStatus.UNDER_REVIEW
        self.version.save(update_fields=["status", "updated_at"])
        response = self.delete_item(
            self.associate,
            self.item.id,
            {"reason": "  Client stopped this product.  "},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ProtocolItem.objects.filter(pk=self.item.id).exists())
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.reason, "Client stopped this product.")

    def test_blank_reason_is_rejected(self):
        edit = self.edit_item(
            self.admin,
            self.item.id,
            self.edit_payload(reason="   "),
        )
        self.assertEqual(edit.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", edit.data["detail"])
        delete = self.delete_item(self.admin, self.item.id, {"reason": "   "})
        self.assertEqual(delete.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", delete.data["detail"])
        self.assertTrue(ProtocolItem.objects.filter(pk=self.item.id).exists())

    def test_other_statuses_are_rejected(self):
        blocked_statuses = (
            ProtocolVersionStatus.APPROVED,
            ProtocolVersionStatus.SCHEDULED,
            ProtocolVersionStatus.ACTIVE,
            ProtocolVersionStatus.SUPERSEDED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        )
        for version_status in blocked_statuses:
            version = publish_current_version(
                self.profile,
                status=version_status,
                name=f"Locked {version_status}",
                purpose="Published",
            )
            item = add_protocol_item(version, self.supplement)
            edit = self.edit_item(self.admin, item.id, self.edit_payload())
            replace = self.replace_item(
                self.admin,
                item.id,
                self.replace_payload(version_id=str(version.id)),
            )
            delete = self.delete_item(
                self.admin,
                item.id,
                {"reason": "Should not apply."},
            )
            for response in (edit, replace, delete):
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    response.data["detail"],
                    "Supplements can only be changed while the version is draft or under review.",
                )
            item.refresh_from_db()
            self.assertEqual(item.dosage, "1 capsule")
            self.assertEqual(item.supplement.pk, self.supplement.pk)
            self.assertFalse(
                ProtocolEvent.objects.filter(protocol_version=version).exists()
            )

    def test_customer_is_forbidden(self):
        edit = self.edit_item(self.customer, self.item.id, self.edit_payload())
        replace = self.replace_item(
            self.customer,
            self.item.id,
            self.replace_payload(),
        )
        delete = self.delete_item(
            self.customer,
            self.item.id,
            {"reason": "Client should not remove this."},
        )
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(replace.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)
        self.item.refresh_from_db()
        self.assertEqual(self.item.dosage, "1 capsule")

    def test_unknown_item_is_not_found(self):
        missing = uuid.uuid4()
        edit = self.edit_item(self.admin, missing, self.edit_payload())
        replace = self.replace_item(self.admin, missing, self.replace_payload())
        delete = self.delete_item(
            self.admin,
            missing,
            {"reason": "Already gone."},
        )
        for response in (edit, replace, delete):
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.data["detail"], "Protocol supplement not found.")


class ProtocolVersionApproveTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-approve-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-approve-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-approve-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-approve-client@example.com",
            "Ava",
            "Shah",
        )
        self.protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.review_on = date(2026, 11, 1)
        self.version = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
            review_on=self.review_on,
            is_ongoing=True,
        )
        self.supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="APPROVE-D3",
        )
        ProtocolItem.objects.create(
            version=self.version,
            supplement=self.supplement,
            dosage="1 capsule",
            frequency=ProtocolItemFrequency.DAILY,
            timing=ProtocolItemTiming.WITH_BREAKFAST,
            duration="90 days",
            instructions="Take 1 capsule with breakfast.",
            rationale="Low vitamin D.",
        )

    def approve_payload(self, **overrides):
        payload = {
            "starts_on": "2026-10-01",
            "ends_on": "2026-12-15",
            "approval_notes": "Ready for the client.",
        }
        payload.update(overrides)
        return payload

    def approve(self, user, version_id, payload):
        request = self.factory.post(
            f"/supplementation/protocol-versions/{version_id}/approve/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionApproveView.as_view()(request, pk=version_id)

    def test_admin_approves_draft(self):
        response = self.approve(
            self.admin,
            self.version.pk,
            self.approve_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"detail": "Protocol version approved."})
        self.version.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.APPROVED)
        self.assertEqual(self.version.starts_on, date(2026, 10, 1))
        self.assertEqual(self.version.ends_on, date(2026, 12, 15))
        self.assertEqual(self.version.approval_notes, "Ready for the client.")
        self.assertEqual(self.version.review_on, self.review_on)
        self.assertTrue(self.version.is_ongoing)
        self.assertEqual(self.version.approved_by.pk, self.admin.pk)
        self.assertIsNotNone(self.version.approved_at)
        self.assertIsNone(self.version.published_at)
        self.assertIsNone(self.protocol.current_version)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.APPROVED)
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(event.customer_profile.pk, self.profile.pk)
        self.assertEqual(event.protocol.pk, self.protocol.pk)
        self.assertEqual(
            event.before,
            {
                "status": "draft",
                "starts_on": None,
                "ends_on": None,
                "approval_notes": None,
            },
        )
        self.assertEqual(
            event.after,
            {
                "status": "approved",
                "starts_on": "2026-10-01",
                "ends_on": "2026-12-15",
                "approval_notes": "Ready for the client.",
            },
        )

    def test_associate_approves_under_review(self):
        self.version.status = ProtocolVersionStatus.UNDER_REVIEW
        self.version.save(update_fields=["status", "updated_at"])
        response = self.approve(
            self.associate,
            self.version.pk,
            self.approve_payload(ends_on=None, approval_notes="  "),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.APPROVED)
        self.assertEqual(self.version.starts_on, date(2026, 10, 1))
        self.assertEqual(self.version.ends_on, date(2026, 12, 30))
        self.assertIsNone(self.version.approval_notes)
        self.assertEqual(self.version.approved_by.pk, self.associate.pk)

    def test_previous_version_stays_active(self):
        active = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=2,
            status=ProtocolVersionStatus.ACTIVE,
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 9, 30),
        )
        self.protocol.current_version = active
        self.protocol.save(update_fields=["current_version", "updated_at"])
        response = self.approve(
            self.admin,
            self.version.pk,
            self.approve_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        active.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(active.status, ProtocolVersionStatus.ACTIVE)
        self.assertEqual(self.protocol.current_version.pk, active.pk)
        self.assertFalse(
            ProtocolEvent.objects.filter(protocol_version=active).exists()
        )

    def test_ends_on_before_starts_on_is_rejected(self):
        response = self.approve(
            self.admin,
            self.version.pk,
            self.approve_payload(starts_on="2026-12-15", ends_on="2026-10-01"),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ends_on", response.data["detail"])
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.DRAFT)

    def test_ends_on_before_today_is_rejected(self):
        today = timezone.localdate()
        response = self.approve(
            self.admin,
            self.version.pk,
            self.approve_payload(
                starts_on=(today - timedelta(days=10)).isoformat(),
                ends_on=(today - timedelta(days=1)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"]["ends_on"],
            ["ends_on must be on or after today."],
        )
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.DRAFT)

    def test_default_ends_on_before_today_is_rejected(self):
        today = timezone.localdate()
        response = self.approve(
            self.admin,
            self.version.pk,
            self.approve_payload(
                starts_on=(today - timedelta(days=100)).isoformat(),
                ends_on=None,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"]["ends_on"],
            ["ends_on must be on or after today."],
        )
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.DRAFT)

    def test_starts_on_is_required(self):
        response = self.approve(
            self.admin,
            self.version.pk,
            {"ends_on": None, "approval_notes": ""},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("starts_on", response.data["detail"])

    def test_other_statuses_are_rejected(self):
        blocked_statuses = (
            ProtocolVersionStatus.APPROVED,
            ProtocolVersionStatus.SCHEDULED,
            ProtocolVersionStatus.ACTIVE,
            ProtocolVersionStatus.SUPERSEDED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        )
        for index, version_status in enumerate(blocked_statuses, start=2):
            version = ProtocolVersion.objects.create(
                protocol=self.protocol,
                version_number=index,
                status=version_status,
            )
            response = self.approve(
                self.admin,
                version.pk,
                self.approve_payload(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data["detail"],
                "Protocol version can only be approved while it is draft or under review.",
            )
            version.refresh_from_db()
            self.assertEqual(version.status, version_status)

    def test_customer_is_forbidden(self):
        response = self.approve(
            self.customer,
            self.version.pk,
            self.approve_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        response = self.approve(
            self.admin,
            uuid.uuid4(),
            self.approve_payload(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")

    def test_version_without_supplements_is_rejected(self):
        empty = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=9,
            status=ProtocolVersionStatus.DRAFT,
        )
        response = self.approve(self.admin, empty.pk, self.approve_payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "Add at least one supplement before approving this version.",
        )
        empty.refresh_from_db()
        self.assertEqual(empty.status, ProtocolVersionStatus.DRAFT)

    def test_inactive_supplement_is_rejected(self):
        self.supplement.is_active = False
        self.supplement.save(update_fields=["is_active", "updated_at"])
        response = self.approve(self.admin, self.version.pk, self.approve_payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Supplement is inactive.")
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.DRAFT)


def customer_plan_get(factory, user, path, profile_id="omit"):
    extra = {}
    if profile_id != "omit":
        extra["HTTP_X_CUSTOMER_PROFILE_ID"] = profile_id
    request = factory.get(path, **extra)
    if user is not None:
        force_authenticate(request, user=user)
    return request


def make_plan_item(version, supplement, **overrides):
    payload = {
        "version": version,
        "supplement": supplement,
        "dosage": "1 capsule",
        "frequency": ProtocolItemFrequency.DAILY,
        "custom_frequency": None,
        "timing": ProtocolItemTiming.WITH_BREAKFAST,
        "duration": "90 days",
        "instructions": "Take with food.",
        "rationale": "Low vitamin D.",
    }
    payload.update(overrides)
    return ProtocolItem.objects.create(**payload)


def add_protocol_item(version, supplement):
    return ProtocolItem.objects.create(
        version=version,
        supplement=supplement,
        dosage="1 capsule",
        frequency=ProtocolItemFrequency.DAILY,
        timing=ProtocolItemTiming.WITH_BREAKFAST,
        duration="90 days",
        instructions="Take 1 capsule with breakfast.",
        rationale="Low vitamin D.",
    )


class ProtocolVersionPublishTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-publish-admin@example.com",
            UserType.ADMIN,
        )
        self.customer = create_staff_user(
            "protocol-publish-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-publish-client@example.com",
            "Ava",
            "Shah",
        )
        self.protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="PUBLISH-D3",
        )
        self.today = timezone.localdate()
        self.version = self.make_version(
            3,
            ProtocolVersionStatus.DRAFT,
            starts_on=None,
        )
        add_protocol_item(self.version, self.supplement)

    def make_version(self, version_number, version_status, starts_on, ends_on=None):
        return ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=version_number,
            status=version_status,
            starts_on=starts_on,
            ends_on=ends_on,
        )

    def approve(self, version, starts_on, ends_on):
        request = self.factory.post(
            f"/supplementation/protocol-versions/{version.pk}/approve/",
            {
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat() if ends_on is not None else None,
                "approval_notes": "",
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        return ProtocolVersionApproveView.as_view()(request, pk=version.pk)

    def publish(self, user, version):
        request = self.factory.post(
            f"/supplementation/protocol-versions/{version.pk}/publish/",
            {},
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionPublishView.as_view()(request, pk=version.pk)

    def test_future_start_schedules_and_supersedes_live_versions(self):
        active = self.make_version(
            1,
            ProtocolVersionStatus.ACTIVE,
            starts_on=self.today - timedelta(days=30),
            ends_on=self.today + timedelta(days=10),
        )
        scheduled = self.make_version(
            2,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today + timedelta(days=3),
            ends_on=self.today + timedelta(days=40),
        )
        draft = self.make_version(
            4,
            ProtocolVersionStatus.DRAFT,
            starts_on=None,
        )
        self.protocol.current_version = active
        self.protocol.save(update_fields=["current_version", "updated_at"])
        starts_on = self.today + timedelta(days=7)
        approved = self.approve(
            self.version,
            starts_on,
            starts_on + timedelta(days=30),
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        response = self.publish(self.admin, self.version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"detail": "Protocol version published."})
        self.version.refresh_from_db()
        active.refresh_from_db()
        scheduled.refresh_from_db()
        draft.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.SCHEDULED)
        self.assertEqual(self.version.published_by.pk, self.admin.pk)
        self.assertIsNotNone(self.version.published_at)
        self.assertEqual(self.version.supersedes.pk, active.pk)
        self.assertEqual(self.protocol.current_version.pk, self.version.pk)
        self.assertEqual(active.status, ProtocolVersionStatus.SUPERSEDED)
        self.assertEqual(scheduled.status, ProtocolVersionStatus.SUPERSEDED)
        self.assertEqual(draft.status, ProtocolVersionStatus.DRAFT)
        approved_event = ProtocolEvent.objects.get(
            protocol_version=self.version,
            action=ProtocolEventAction.APPROVED,
        )
        self.assertTrue(approved_event.client_visible)
        scheduled_event = ProtocolEvent.objects.get(
            protocol_version=self.version,
            action=ProtocolEventAction.SCHEDULED,
        )
        self.assertTrue(scheduled_event.client_visible)
        self.assertEqual(
            ProtocolEvent.objects.filter(
                action=ProtocolEventAction.SUPERSEDED,
                client_visible=True,
            ).count(),
            2,
        )

    def test_start_today_publishes_active(self):
        approved = self.approve(
            self.version,
            self.today,
            self.today + timedelta(days=30),
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        response = self.publish(self.admin, self.version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.ACTIVE)
        self.assertTrue(
            ProtocolEvent.objects.filter(
                protocol_version=self.version,
                action=ProtocolEventAction.PUBLISHED,
                client_visible=True,
            ).exists()
        )

    def test_version_without_supplements_is_rejected(self):
        empty = self.make_version(
            8,
            ProtocolVersionStatus.APPROVED,
            starts_on=self.today,
        )
        response = self.publish(self.admin, empty)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "Add at least one supplement before publishing this version.",
        )

    def test_inactive_supplement_is_rejected(self):
        approved = self.approve(
            self.version,
            self.today,
            self.today + timedelta(days=30),
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        self.supplement.is_active = False
        self.supplement.save(update_fields=["is_active", "updated_at"])
        response = self.publish(self.admin, self.version)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Supplement is inactive.")
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.APPROVED)

    def test_draft_is_rejected(self):
        response = self.publish(self.admin, self.version)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "Protocol version can only be published while it is approved.",
        )

    def test_customer_is_forbidden(self):
        response = self.publish(self.customer, self.version)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        missing = ProtocolVersion(pk=uuid.uuid4())
        response = self.publish(self.admin, missing)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")

    def test_second_publish_is_rejected(self):
        approved = self.approve(
            self.version,
            self.today,
            self.today + timedelta(days=30),
        )
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        first = self.publish(self.admin, self.version)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self.publish(self.admin, self.version)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            second.data["detail"],
            "Protocol version can only be published while it is approved.",
        )


class ProtocolVersionSweepTests(TestCase):
    def setUp(self):
        self.profile = create_profile(
            "protocol-sweep-client@example.com",
            "Ava",
            "Shah",
        )
        self.protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.today = date(2026, 10, 28)

    def make_version(self, version_number, version_status, starts_on, ends_on=None):
        return ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=version_number,
            status=version_status,
            starts_on=starts_on,
            ends_on=ends_on,
        )

    def test_due_scheduled_version_becomes_active(self):
        version = self.make_version(
            1,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=10),
        )
        self.protocol.current_version = version
        self.protocol.save(update_fields=["current_version", "updated_at"])
        expired_count, activated_count = sweep_protocol_versions(self.today)
        self.assertEqual(expired_count, 0)
        self.assertEqual(activated_count, 1)
        version.refresh_from_db()
        self.assertEqual(version.status, ProtocolVersionStatus.ACTIVE)
        expired_count, activated_count = sweep_protocol_versions(self.today)
        self.assertEqual(expired_count, 0)
        self.assertEqual(activated_count, 0)

    def test_future_scheduled_version_stays_scheduled(self):
        version = self.make_version(
            1,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today + timedelta(days=7),
            ends_on=self.today + timedelta(days=30),
        )
        sweep_protocol_versions(self.today)
        version.refresh_from_db()
        self.assertEqual(version.status, ProtocolVersionStatus.SCHEDULED)

    def test_ended_version_expires_and_stays_active_on_its_end_date(self):
        ended = self.make_version(
            1,
            ProtocolVersionStatus.ACTIVE,
            starts_on=self.today - timedelta(days=90),
            ends_on=self.today - timedelta(days=1),
        )
        ending_today = self.make_version(
            2,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today - timedelta(days=5),
            ends_on=self.today,
        )
        self.protocol.current_version = ending_today
        self.protocol.save(update_fields=["current_version", "updated_at"])
        sweep_protocol_versions(self.today)
        ended.refresh_from_db()
        ending_today.refresh_from_db()
        self.assertEqual(ended.status, ProtocolVersionStatus.EXPIRED)
        self.assertEqual(ending_today.status, ProtocolVersionStatus.ACTIVE)

    def test_due_scheduled_with_a_passed_end_date_expires(self):
        version = self.make_version(
            1,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today - timedelta(days=20),
            ends_on=self.today - timedelta(days=1),
        )
        expired_count, activated_count = sweep_protocol_versions(self.today)
        self.assertEqual(expired_count, 1)
        self.assertEqual(activated_count, 0)
        version.refresh_from_db()
        self.assertEqual(version.status, ProtocolVersionStatus.EXPIRED)

    def test_current_due_version_activates_and_other_due_version_is_superseded(self):
        current = self.make_version(
            1,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today - timedelta(days=1),
            ends_on=self.today + timedelta(days=20),
        )
        later = self.make_version(
            2,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=20),
        )
        self.protocol.current_version = current
        self.protocol.save(update_fields=["current_version", "updated_at"])
        sweep_protocol_versions(self.today)
        current.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(current.status, ProtocolVersionStatus.ACTIVE)
        self.assertEqual(later.status, ProtocolVersionStatus.SUPERSEDED)
        self.assertFalse(ProtocolEvent.objects.exists())

    def test_due_versions_on_separate_protocols_both_activate(self):
        other_profile = create_profile(
            "protocol-sweep-other@example.com",
            "Noah",
            "Shah",
        )
        other_protocol = Protocol.objects.create(
            customer_profile=other_profile,
            name="Second protocol",
            purpose="Separate window",
        )
        first = self.make_version(
            1,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=10),
        )
        second = ProtocolVersion.objects.create(
            protocol=other_protocol,
            version_number=1,
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=10),
        )
        expired_count, activated_count = sweep_protocol_versions(self.today)
        self.assertEqual(expired_count, 0)
        self.assertEqual(activated_count, 2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, ProtocolVersionStatus.ACTIVE)
        self.assertEqual(second.status, ProtocolVersionStatus.ACTIVE)
        self.protocol.refresh_from_db()
        other_protocol.refresh_from_db()
        self.assertEqual(self.protocol.current_version_id, first.id)
        self.assertEqual(other_protocol.current_version_id, second.id)

    def test_existing_active_version_is_left_in_place(self):
        active = self.make_version(
            1,
            ProtocolVersionStatus.ACTIVE,
            starts_on=self.today - timedelta(days=10),
            ends_on=self.today + timedelta(days=20),
        )
        scheduled = self.make_version(
            2,
            ProtocolVersionStatus.SCHEDULED,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=20),
        )
        self.protocol.current_version = active
        self.protocol.save(update_fields=["current_version", "updated_at"])
        expired_count, activated_count = sweep_protocol_versions(self.today)
        self.assertEqual(expired_count, 0)
        self.assertEqual(activated_count, 0)
        active.refresh_from_db()
        scheduled.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(active.status, ProtocolVersionStatus.ACTIVE)
        self.assertEqual(scheduled.status, ProtocolVersionStatus.SCHEDULED)
        self.assertEqual(self.protocol.current_version_id, active.id)


class PlanSummaryTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_profile("plan-summary@example.com", "Ava", "Shah")
        self.customer = self.profile.customer.user
        UserAccount.objects.create(
            user=self.customer,
            account_type=UserType.CUSTOMER,
        )
        self.admin = create_staff_user("plan-summary-admin@example.com", UserType.ADMIN)
        self.other = create_profile("plan-summary-other@example.com", "Noah", "Kim")
        self.empty = CustomerProfile.objects.create(
            customer=self.profile.customer,
            first_name="Kid",
            last_name="Shah",
            is_main=False,
        )
        self.inactive_profile = CustomerProfile.objects.create(
            customer=self.profile.customer,
            first_name="Old",
            last_name="Shah",
            is_main=False,
            is_active=False,
        )
        today = timezone.localdate()
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="In window",
            purpose="Started",
            starts_on=today - timedelta(days=1),
            ends_on=today + timedelta(days=10),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Current",
            purpose="Live",
            starts_on=today - timedelta(days=5),
            ends_on=today + timedelta(days=20),
            version_number=2,
            previous_status=ProtocolVersionStatus.SUPERSEDED,
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Later",
            purpose="Soon",
            starts_on=today + timedelta(days=7),
            ends_on=today + timedelta(days=30),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.APPROVED,
            name="Preparing",
            purpose="Approved",
            starts_on=today + timedelta(days=14),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.CANCELLED,
            name="Cancelled",
            purpose="Stopped",
            starts_on=today - timedelta(days=30),
            ends_on=today - timedelta(days=1),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Ended",
            purpose="Past",
            starts_on=today - timedelta(days=40),
            ends_on=today - timedelta(days=1),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Draft",
            purpose="Hidden",
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.UNDER_REVIEW,
            name="Review",
            purpose="Hidden",
        )
        inactive = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Inactive protocol",
            purpose="Hidden",
            starts_on=today,
        )
        inactive.protocol.is_active = False
        inactive.protocol.save(update_fields=["is_active", "updated_at"])

    def summary(self, user, profile_id="omit"):
        extra = {}
        if profile_id != "omit":
            extra["HTTP_X_CUSTOMER_PROFILE_ID"] = profile_id
        request = self.factory.get("/supplementation/plan/summary/", **extra)
        if user is not None:
            force_authenticate(request, user=user)
        return PlanSummaryView.as_view()(request)

    def test_customer_receives_status_counts(self):
        response = self.summary(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Protocol summary retrieved successfully.",
        )
        self.assertEqual(
            response.data["data"],
            {"active": 2, "coming_up": 1, "preparing": 2, "historical": 2},
        )

    def test_unset_current_version_draft_counts_as_preparing(self):
        protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Unpublished",
            purpose="Still a draft",
        )
        ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
        )
        response = self.summary(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["preparing"], 3)

    def test_later_draft_does_not_add_a_second_preparing_count(self):
        current = Protocol.objects.get(
            customer_profile=self.profile,
            name="Current",
        )
        ProtocolVersion.objects.create(
            protocol=current,
            version_number=3,
            status=ProtocolVersionStatus.DRAFT,
        )
        response = self.summary(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["preparing"], 2)

    def test_empty_profile_returns_zeros(self):
        response = self.summary(self.customer, str(self.empty.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"],
            {"active": 0, "coming_up": 0, "preparing": 0, "historical": 0},
        )

    def test_missing_header_is_not_found(self):
        response = self.summary(self.customer)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Customer profile not found.")

    def test_other_customers_profile_is_not_found(self):
        response = self.summary(self.customer, str(self.other.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_profile_is_not_found(self):
        response = self.summary(self.customer, str(uuid.uuid4()))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_junk_profile_header_is_not_found(self):
        response = self.summary(self.customer, "not-a-uuid")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_profile_is_not_found(self):
        response = self.summary(self.customer, str(self.inactive_profile.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_is_forbidden(self):
        response = self.summary(self.admin, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_is_unauthorized(self):
        response = self.summary(None, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProtocolVersionCreateTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-version-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-version-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-version-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-version-client@example.com",
            "Ava",
            "Shah",
        )
        self.other_profile = create_profile(
            "protocol-version-other@example.com",
            "Noah",
            "Kim",
        )
        today = timezone.localdate()
        self.source = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Sleep & Recovery",
            purpose="Faster sleep onset and deeper sleep",
            starts_on=today,
        )
        self.protocol = self.source.protocol
        self.supplement = create_supplement(
            self.admin,
            name="Vitamin D3",
            sku="VERSION-D3",
        )
        self.item = ProtocolItem.objects.create(
            version=self.source,
            supplement=self.supplement,
            dosage="1 capsule",
            frequency=ProtocolItemFrequency.DAILY,
            timing=ProtocolItemTiming.WITH_BREAKFAST,
            duration="90 days",
            instructions="Take 1 capsule with breakfast.",
            rationale="Low vitamin D.",
        )

    def create_version(self, user, protocol_id, payload):
        request = self.factory.post(
            f"/supplementation/protocols/{protocol_id}/versions/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionCreateView.as_view()(request, pk=protocol_id)

    def test_scratch_creates_the_next_draft(self):
        response = self.create_version(
            self.admin,
            self.protocol.id,
            {"summary_notes": "Reset after the April panel"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["detail"], "Protocol version created.")
        version = ProtocolVersion.objects.get(
            pk=response.data["data"]["new_protocol_version_id"],
        )
        self.protocol.refresh_from_db()
        self.assertEqual(version.protocol_id, self.protocol.id)
        self.assertEqual(version.version_number, 2)
        self.assertEqual(version.status, ProtocolVersionStatus.DRAFT)
        self.assertEqual(version.summary_notes, "Reset after the April panel")
        self.assertIsNone(version.notes)
        self.assertFalse(version.is_ongoing)
        self.assertIsNone(version.starts_on)
        self.assertEqual(self.protocol.current_version_id, self.source.id)
        self.assertEqual(self.protocol.name, "Sleep & Recovery")
        self.assertFalse(version.items.exists())
        drafted = ProtocolEvent.objects.get(protocol_version=version)
        self.assertEqual(drafted.action, ProtocolEventAction.VERSION_DRAFTED)
        self.assertFalse(drafted.client_visible)
        self.assertEqual(drafted.actor_id, self.admin.id)
        self.assertEqual(
            drafted.after,
            {"version_number": 2, "status": "draft"},
        )
        self.assertFalse(
            ProtocolEvent.objects.filter(
                protocol=self.protocol,
                action=ProtocolEventAction.PROTOCOL_CREATED,
            ).exists()
        )

    def test_blank_summary_stores_null(self):
        response = self.create_version(
            self.associate,
            self.protocol.id,
            {"summary_notes": "  "},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        version = ProtocolVersion.objects.get(
            pk=response.data["data"]["new_protocol_version_id"],
        )
        self.assertIsNone(version.summary_notes)
        self.assertEqual(version.version_number, 2)

    def test_omitted_summary_stores_null(self):
        response = self.create_version(self.admin, self.protocol.id, {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        version = ProtocolVersion.objects.get(
            pk=response.data["data"]["new_protocol_version_id"],
        )
        self.assertIsNone(version.summary_notes)

    def test_clone_copies_items_and_keeps_protocol_identity(self):
        response = self.create_version(
            self.associate,
            self.protocol.id,
            {
                "source_version_id": str(self.source.id),
                "summary_notes": "Cloned from the active plan",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        version = ProtocolVersion.objects.get(
            pk=response.data["data"]["new_protocol_version_id"],
        )
        self.protocol.refresh_from_db()
        self.assertEqual(version.version_number, 2)
        self.assertEqual(version.status, ProtocolVersionStatus.DRAFT)
        self.assertEqual(version.summary_notes, "Cloned from the active plan")
        self.assertIsNone(version.notes)
        self.assertEqual(self.protocol.current_version_id, self.source.id)
        self.assertEqual(self.protocol.name, "Sleep & Recovery")
        self.assertEqual(self.protocol.purpose, "Faster sleep onset and deeper sleep")
        cloned = version.items.get()
        self.assertEqual(cloned.supplement_id, self.item.supplement_id)
        self.assertEqual(cloned.dosage, self.item.dosage)
        self.assertEqual(cloned.frequency, self.item.frequency)
        self.assertEqual(cloned.timing, self.item.timing)
        self.assertEqual(cloned.duration, self.item.duration)
        self.assertEqual(cloned.instructions, self.item.instructions)
        self.assertEqual(cloned.rationale, self.item.rationale)
        self.assertNotEqual(cloned.id, self.item.id)
        drafted = ProtocolEvent.objects.get(protocol_version=version)
        self.assertEqual(
            drafted.after,
            {
                "version_number": 2,
                "status": "draft",
                "source_version_id": str(self.source.id),
            },
        )

    def test_inactive_source_supplement_is_rejected(self):
        self.supplement.is_active = False
        self.supplement.save(update_fields=["is_active", "updated_at"])
        response = self.create_version(
            self.admin,
            self.protocol.id,
            {"source_version_id": str(self.source.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Supplement is inactive.",
            response.data["detail"]["source_version_id"],
        )
        self.assertEqual(self.protocol.versions.count(), 1)

    def test_unapproved_source_is_rejected(self):
        blocked_statuses = (
            ProtocolVersionStatus.DRAFT,
            ProtocolVersionStatus.UNDER_REVIEW,
        )
        for version_status in blocked_statuses:
            source = publish_current_version(
                self.profile,
                status=version_status,
                name="Draft plan",
                purpose="Not approved",
            )
            response = self.create_version(
                self.admin,
                self.protocol.id,
                {
                    "source_version_id": str(source.id),
                    "summary_notes": "Should fail",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data["detail"],
                "Protocol version can only be copied once it is approved.",
            )
        self.assertEqual(self.protocol.versions.count(), 1)

    def test_approved_and_later_statuses_can_be_copied(self):
        copyable_statuses = (
            ProtocolVersionStatus.APPROVED,
            ProtocolVersionStatus.SCHEDULED,
            ProtocolVersionStatus.SUPERSEDED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        )
        for version_status in copyable_statuses:
            source = publish_current_version(
                self.profile,
                status=version_status,
                name="Ready plan",
                purpose="Already approved",
            )
            ProtocolItem.objects.create(
                version=source,
                supplement=self.supplement,
                dosage="1 capsule",
                frequency=ProtocolItemFrequency.DAILY,
                timing=ProtocolItemTiming.WITH_BREAKFAST,
                duration="90 days",
                instructions="Take 1 capsule with breakfast.",
                rationale="Low vitamin D.",
            )
            response = self.create_version(
                self.admin,
                self.protocol.id,
                {
                    "source_version_id": str(source.id),
                    "summary_notes": "Copied",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            version = ProtocolVersion.objects.get(
                pk=response.data["data"]["new_protocol_version_id"],
            )
            self.assertEqual(version.items.count(), 1)

    def test_source_on_another_profile_is_not_found(self):
        other = publish_current_version(
            self.other_profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Other",
            purpose="Someone else",
        )
        response = self.create_version(
            self.admin,
            self.protocol.id,
            {
                "source_version_id": str(other.id),
                "summary_notes": "Copied",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")

    def test_unknown_source_is_not_found(self):
        response = self.create_version(
            self.admin,
            self.protocol.id,
            {
                "source_version_id": str(uuid.uuid4()),
                "summary_notes": "Copied",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_protocol_is_not_found(self):
        response = self.create_version(
            self.admin,
            uuid.uuid4(),
            {"summary_notes": "New draft"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_protocol_still_accepts_a_draft(self):
        self.protocol.is_active = False
        self.protocol.save(update_fields=["is_active", "updated_at"])
        response = self.create_version(
            self.admin,
            self.protocol.id,
            {"summary_notes": "Still editable"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_customer_is_forbidden(self):
        response = self.create_version(
            self.customer,
            self.protocol.id,
            {"summary_notes": "No"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ProtocolVersionCancelTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-cancel-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-cancel-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-cancel-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-cancel-client@example.com",
            "Ava",
            "Shah",
        )
        self.protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.version = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=2,
            status=ProtocolVersionStatus.APPROVED,
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 12, 15),
            approval_notes="Ready for the client.",
        )

    def cancel(self, user, version_id, payload):
        request = self.factory.post(
            f"/supplementation/protocol-versions/{version_id}/cancel/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionCancelView.as_view()(request, pk=version_id)

    def test_admin_cancels_approved_version(self):
        response = self.cancel(
            self.admin,
            self.version.pk,
            {"reason": "Protocol ended early"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"detail": "Protocol version cancelled."})
        self.version.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.CANCELLED)
        self.assertEqual(self.version.cancellation_reason, "Protocol ended early")
        self.assertEqual(self.version.cancelled_by.pk, self.admin.pk)
        self.assertIsNotNone(self.version.cancelled_at)
        self.assertEqual(self.version.starts_on, date(2026, 10, 1))
        self.assertEqual(self.version.ends_on, date(2026, 12, 15))
        self.assertIsNone(self.protocol.current_version)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.CANCELLED)
        self.assertFalse(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(
            event.before,
            {
                "status": "approved",
                "starts_on": "2026-10-01",
                "ends_on": "2026-12-15",
                "approval_notes": "Ready for the client.",
            },
        )
        self.assertEqual(
            event.after,
            {
                "status": "cancelled",
                "starts_on": "2026-10-01",
                "ends_on": "2026-12-15",
                "approval_notes": "Ready for the client.",
            },
        )

    def test_associate_cancels_active_version_and_keeps_current(self):
        predecessor = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=1,
            status=ProtocolVersionStatus.SUPERSEDED,
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 9, 30),
        )
        self.version.status = ProtocolVersionStatus.ACTIVE
        self.version.save(update_fields=["status", "updated_at"])
        self.protocol.current_version = self.version
        self.protocol.save(update_fields=["current_version", "updated_at"])
        response = self.cancel(
            self.associate,
            self.version.pk,
            {"reason": "  Stop this plan  "},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        predecessor.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.CANCELLED)
        self.assertEqual(self.version.cancellation_reason, "Stop this plan")
        self.assertEqual(self.version.cancelled_by.pk, self.associate.pk)
        self.assertEqual(self.protocol.current_version.pk, self.version.pk)
        self.assertEqual(predecessor.status, ProtocolVersionStatus.SUPERSEDED)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertTrue(event.client_visible)
        self.assertFalse(
            ProtocolEvent.objects.filter(protocol_version=predecessor).exists()
        )

    def test_scheduled_cancel_is_client_visible(self):
        self.version.status = ProtocolVersionStatus.SCHEDULED
        self.version.save(update_fields=["status", "updated_at"])
        self.protocol.current_version = self.version
        self.protocol.save(update_fields=["current_version", "updated_at"])
        response = self.cancel(
            self.admin,
            self.version.pk,
            {"reason": "Start date moved"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.CANCELLED)
        self.assertEqual(self.protocol.current_version.pk, self.version.pk)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertTrue(event.client_visible)
        self.assertEqual(event.before["status"], "scheduled")

    def test_blank_reason_is_rejected(self):
        response = self.cancel(self.admin, self.version.pk, {"reason": "   "})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", response.data["detail"])
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.APPROVED)

    def test_reason_is_required(self):
        response = self.cancel(self.admin, self.version.pk, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", response.data["detail"])

    def test_other_statuses_are_rejected(self):
        blocked_statuses = (
            ProtocolVersionStatus.DRAFT,
            ProtocolVersionStatus.UNDER_REVIEW,
            ProtocolVersionStatus.SUPERSEDED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        )
        for index, version_status in enumerate(blocked_statuses, start=3):
            version = ProtocolVersion.objects.create(
                protocol=self.protocol,
                version_number=index,
                status=version_status,
                starts_on=date(2026, 10, 1),
                ends_on=date(2026, 12, 15),
            )
            response = self.cancel(
                self.admin,
                version.pk,
                {"reason": "Too late"},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data["detail"],
                "Protocol version can only be cancelled after it is approved.",
            )
            version.refresh_from_db()
            self.assertEqual(version.status, version_status)
            self.assertFalse(
                ProtocolEvent.objects.filter(protocol_version=version).exists()
            )

    def test_customer_is_forbidden(self):
        response = self.cancel(
            self.customer,
            self.version.pk,
            {"reason": "No"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        response = self.cancel(
            self.admin,
            uuid.uuid4(),
            {"reason": "Missing"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")


class ProtocolVersionExtendTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_staff_user(
            "protocol-extend-admin@example.com",
            UserType.ADMIN,
        )
        self.associate = create_staff_user(
            "protocol-extend-associate@example.com",
            UserType.ASSOCIATE,
        )
        self.customer = create_staff_user(
            "protocol-extend-customer@example.com",
            UserType.CUSTOMER,
        )
        self.profile = create_profile(
            "protocol-extend-client@example.com",
            "Ava",
            "Shah",
        )
        self.protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Foundational Health",
            purpose="Close nutritional gaps",
        )
        self.today = timezone.localdate()
        self.version = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=2,
            status=ProtocolVersionStatus.ACTIVE,
            starts_on=self.today - timedelta(days=10),
            ends_on=self.today + timedelta(days=20),
            approval_notes="Ready for the client.",
        )
        self.protocol.current_version = self.version
        self.protocol.save(update_fields=["current_version", "updated_at"])

    def extend(self, user, version_id, payload):
        request = self.factory.patch(
            f"/supplementation/protocol-versions/{version_id}/extend/",
            payload,
            format="json",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return ProtocolVersionExtendView.as_view()(request, pk=version_id)

    def test_admin_extends_active_version(self):
        new_ends_on = self.today + timedelta(days=50)
        response = self.extend(
            self.admin,
            self.version.pk,
            {"ends_on": new_ends_on.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"detail": "Protocol version extended."})
        self.version.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.ACTIVE)
        self.assertEqual(self.version.ends_on, new_ends_on)
        self.assertEqual(self.version.starts_on, self.today - timedelta(days=10))
        self.assertEqual(self.version.approval_notes, "Ready for the client.")
        self.assertEqual(self.protocol.current_version.pk, self.version.pk)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertEqual(event.action, ProtocolEventAction.EXTENDED)
        self.assertTrue(event.client_visible)
        self.assertEqual(event.actor.pk, self.admin.pk)
        self.assertEqual(
            event.before,
            {
                "status": "active",
                "starts_on": (self.today - timedelta(days=10)).isoformat(),
                "ends_on": (self.today + timedelta(days=20)).isoformat(),
                "approval_notes": "Ready for the client.",
            },
        )
        self.assertEqual(
            event.after,
            {
                "status": "active",
                "starts_on": (self.today - timedelta(days=10)).isoformat(),
                "ends_on": new_ends_on.isoformat(),
                "approval_notes": "Ready for the client.",
            },
        )

    def test_associate_extends_scheduled_version(self):
        self.version.status = ProtocolVersionStatus.SCHEDULED
        self.version.starts_on = self.today + timedelta(days=5)
        self.version.ends_on = self.today + timedelta(days=40)
        self.version.save(
            update_fields=["status", "starts_on", "ends_on", "updated_at"]
        )
        new_ends_on = self.today + timedelta(days=80)
        response = self.extend(
            self.associate,
            self.version.pk,
            {"ends_on": new_ends_on.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.version.refresh_from_db()
        self.protocol.refresh_from_db()
        self.assertEqual(self.version.status, ProtocolVersionStatus.SCHEDULED)
        self.assertEqual(self.version.ends_on, new_ends_on)
        self.assertEqual(self.version.starts_on, self.today + timedelta(days=5))
        self.assertEqual(self.protocol.current_version.pk, self.version.pk)
        event = ProtocolEvent.objects.get(protocol_version=self.version)
        self.assertTrue(event.client_visible)
        self.assertEqual(event.before["status"], "scheduled")

    def test_ends_on_is_required(self):
        response = self.extend(self.admin, self.version.pk, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ends_on", response.data["detail"])

    def test_ends_on_before_starts_on_is_rejected(self):
        self.version.starts_on = self.today + timedelta(days=5)
        self.version.ends_on = self.today + timedelta(days=40)
        self.version.save(update_fields=["starts_on", "ends_on", "updated_at"])
        response = self.extend(
            self.admin,
            self.version.pk,
            {"ends_on": self.today.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ends_on", response.data["detail"])
        self.version.refresh_from_db()
        self.assertEqual(self.version.ends_on, self.today + timedelta(days=40))

    def test_ends_on_before_today_is_rejected(self):
        response = self.extend(
            self.admin,
            self.version.pk,
            {"ends_on": (self.today - timedelta(days=1)).isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"]["ends_on"],
            ["ends_on must be on or after today."],
        )
        self.version.refresh_from_db()
        self.assertEqual(self.version.ends_on, self.today + timedelta(days=20))

    def test_ends_on_not_after_current_is_rejected(self):
        response = self.extend(
            self.admin,
            self.version.pk,
            {"ends_on": self.version.ends_on.isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"]["ends_on"],
            ["ends_on must be after the current end date."],
        )

    def test_open_ended_version_is_rejected(self):
        self.version.ends_on = None
        self.version.save(update_fields=["ends_on", "updated_at"])
        response = self.extend(
            self.admin,
            self.version.pk,
            {"ends_on": (self.today + timedelta(days=30)).isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "This version has no end date to extend.",
        )
        self.version.refresh_from_db()
        self.assertIsNone(self.version.ends_on)
        self.assertFalse(
            ProtocolEvent.objects.filter(protocol_version=self.version).exists()
        )

    def test_other_statuses_are_rejected(self):
        blocked_statuses = (
            ProtocolVersionStatus.DRAFT,
            ProtocolVersionStatus.UNDER_REVIEW,
            ProtocolVersionStatus.APPROVED,
            ProtocolVersionStatus.SUPERSEDED,
            ProtocolVersionStatus.EXPIRED,
            ProtocolVersionStatus.CANCELLED,
        )
        for index, version_status in enumerate(blocked_statuses, start=3):
            version = ProtocolVersion.objects.create(
                protocol=self.protocol,
                version_number=index,
                status=version_status,
                starts_on=self.today - timedelta(days=10),
                ends_on=self.today + timedelta(days=20),
            )
            response = self.extend(
                self.admin,
                version.pk,
                {"ends_on": (self.today + timedelta(days=60)).isoformat()},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data["detail"],
                "Protocol version can only be extended while it is scheduled or active.",
            )
            version.refresh_from_db()
            self.assertEqual(version.status, version_status)
            self.assertEqual(version.ends_on, self.today + timedelta(days=20))
            self.assertFalse(
                ProtocolEvent.objects.filter(protocol_version=version).exists()
            )

    def test_customer_is_forbidden(self):
        response = self.extend(
            self.customer,
            self.version.pk,
            {"ends_on": (self.today + timedelta(days=50)).isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_version_is_not_found(self):
        response = self.extend(
            self.admin,
            uuid.uuid4(),
            {"ends_on": (self.today + timedelta(days=50)).isoformat()},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Protocol version not found.")


class PlanRoutineTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_profile("plan-routine@example.com", "Ava", "Shah")
        self.customer = self.profile.customer.user
        UserAccount.objects.create(
            user=self.customer,
            account_type=UserType.CUSTOMER,
        )
        self.admin = create_staff_user("plan-routine-admin@example.com", UserType.ADMIN)
        today = timezone.localdate()
        self.ends_on = today + timedelta(days=30)
        self.active = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Foundational Health",
            purpose="Gaps",
            starts_on=today - timedelta(days=5),
            ends_on=self.ends_on,
        )
        self.vitamin = create_supplement(self.admin, name="Vitamin D3", sku="ROUTINE-D3")
        self.magnesium = create_supplement(
            self.admin,
            name="Magnesium Glycinate",
            sku="ROUTINE-MAG",
        )
        self.breakfast = make_plan_item(self.active, self.vitamin)
        self.evening = make_plan_item(
            self.active,
            self.magnesium,
            dosage="2 capsules",
            timing=ProtocolItemTiming.AFTER_DINNER,
            instructions="Take in the evening.",
            rationale="Sleep support.",
        )
        scheduled = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Later",
            purpose="Soon",
            starts_on=today + timedelta(days=7),
            ends_on=today + timedelta(days=40),
        )
        later = create_supplement(self.admin, name="Creatine", sku="ROUTINE-CRE")
        make_plan_item(scheduled, later)
        inactive = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Hidden",
            purpose="Inactive",
            starts_on=today,
        )
        hidden = create_supplement(self.admin, name="Hidden Product", sku="ROUTINE-HID")
        make_plan_item(inactive, hidden)
        inactive.protocol.is_active = False
        inactive.protocol.save(update_fields=["is_active", "updated_at"])

    def routine(self, user, profile_id="omit"):
        request = customer_plan_get(
            self.factory,
            user,
            "/supplementation/plan/routine/",
            profile_id,
        )
        return PlanRoutineView.as_view()(request)

    def test_customer_receives_active_items_grouped_by_timing(self):
        response = self.routine(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Active supplements retrieved successfully.",
        )
        self.assertEqual(
            response.data["data"],
            {
                "timings": [
                    {
                        "timing": "with_breakfast",
                        "items": [
                            {
                                "id": str(self.breakfast.id),
                                "supplement": {
                                    "id": str(self.vitamin.id),
                                    "product_name": "Vitamin D3",
                                    "brand_name": self.vitamin.brand.name,
                                    "form": "capsule",
                                },
                                "dosage": "1 capsule",
                                "frequency": "daily",
                                "custom_frequency": None,
                                "timing": "with_breakfast",
                                "ends_on": self.ends_on.isoformat(),
                                "instructions": "Take with food.",
                                "rationale": "Low vitamin D.",
                            }
                        ],
                    },
                    {
                        "timing": "after_dinner",
                        "items": [
                            {
                                "id": str(self.evening.id),
                                "supplement": {
                                    "id": str(self.magnesium.id),
                                    "product_name": "Magnesium Glycinate",
                                    "brand_name": self.magnesium.brand.name,
                                    "form": "capsule",
                                },
                                "dosage": "2 capsules",
                                "frequency": "daily",
                                "custom_frequency": None,
                                "timing": "after_dinner",
                                "ends_on": self.ends_on.isoformat(),
                                "instructions": "Take in the evening.",
                                "rationale": "Sleep support.",
                            }
                        ],
                    },
                ]
            },
        )
        self.assertNotIn("protocol", response.data["data"]["timings"][0]["items"][0])

    def test_ended_active_version_is_hidden(self):
        today = timezone.localdate()
        ended = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Ended",
            purpose="Past",
            starts_on=today - timedelta(days=20),
            ends_on=today - timedelta(days=1),
        )
        ended_product = create_supplement(
            self.admin,
            name="Ended Product",
            sku="ROUTINE-END",
        )
        make_plan_item(ended, ended_product)
        still_open = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Today",
            purpose="Still open",
            starts_on=today - timedelta(days=2),
            ends_on=today,
        )
        today_product = create_supplement(
            self.admin,
            name="Today Product",
            sku="ROUTINE-TODAY",
        )
        make_plan_item(still_open, today_product)
        response = self.routine(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [
            item["supplement"]["product_name"]
            for slot in response.data["data"]["timings"]
            for item in slot["items"]
        ]
        self.assertNotIn("Ended Product", names)
        self.assertIn("Today Product", names)
        self.assertIn("Vitamin D3", names)

    def test_empty_plan_returns_no_timings(self):
        empty = CustomerProfile.objects.create(
            customer=self.profile.customer,
            first_name="Kid",
            last_name="Shah",
            is_main=False,
        )
        response = self.routine(self.customer, str(empty.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], {"timings": []})

    def test_missing_header_is_not_found(self):
        response = self.routine(self.customer)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "Customer profile not found.")

    def test_staff_is_forbidden(self):
        response = self.routine(self.admin, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PlanProtocolListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_profile("plan-protocols@example.com", "Ava", "Shah")
        self.customer = self.profile.customer.user
        UserAccount.objects.create(
            user=self.customer,
            account_type=UserType.CUSTOMER,
        )
        self.admin = create_staff_user(
            "plan-protocols-admin@example.com",
            UserType.ADMIN,
        )
        today = timezone.localdate()
        self.later_active = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Later Active",
            purpose="Newer start",
            starts_on=today,
            ends_on=today + timedelta(days=20),
        )
        self.earlier_active = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Earlier Active",
            purpose="Older start",
            starts_on=today - timedelta(days=10),
            ends_on=today - timedelta(days=1),
        )
        self.later_vitamin = make_plan_item(
            self.later_active,
            create_supplement(self.admin, name="Vitamin D3", sku="PLAN-LIST-D3"),
        )
        self.later_magnesium = make_plan_item(
            self.later_active,
            create_supplement(self.admin, name="Magnesium", sku="PLAN-LIST-MAG"),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SCHEDULED,
            name="Coming",
            purpose="Future",
            starts_on=today + timedelta(days=7),
            ends_on=today + timedelta(days=30),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.CANCELLED,
            name="Stopped",
            purpose="Cancelled",
            starts_on=today - timedelta(days=40),
            ends_on=today - timedelta(days=2),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.EXPIRED,
            name="Finished",
            purpose="Expired",
            starts_on=today - timedelta(days=80),
            ends_on=today - timedelta(days=3),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Scratch",
            purpose="Draft current",
        )
        unpublished = Protocol.objects.create(
            customer_profile=self.profile,
            name="Unpublished",
            purpose="No current",
        )
        ProtocolVersion.objects.create(
            protocol=unpublished,
            version_number=1,
            status=ProtocolVersionStatus.DRAFT,
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.APPROVED,
            name="Approved",
            purpose="Omit",
            starts_on=today + timedelta(days=14),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.UNDER_REVIEW,
            name="Review",
            purpose="Omit",
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.SUPERSEDED,
            name="Old",
            purpose="Omit",
            starts_on=today - timedelta(days=100),
        )
        inactive = publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.ACTIVE,
            name="Inactive",
            purpose="Hidden",
            starts_on=today,
        )
        inactive.protocol.is_active = False
        inactive.protocol.save(update_fields=["is_active", "updated_at"])

    def protocols(self, user, profile_id="omit"):
        request = customer_plan_get(
            self.factory,
            user,
            "/supplementation/plan/protocols/",
            profile_id,
        )
        return PlanProtocolListView.as_view()(request)

    def test_customer_receives_stored_status_summary_and_lists(self):
        response = self.protocols(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Protocols retrieved successfully.",
        )
        data = response.data["data"]
        self.assertEqual(
            data["summary"],
            {
                "active": 2,
                "scheduled": 1,
                "draft": 2,
                "cancelled": 1,
                "expired": 1,
            },
        )
        self.assertEqual(
            [row["name"] for row in data["active"]],
            ["Later Active", "Earlier Active"],
        )
        self.assertEqual(
            data["active"][0],
            {
                "id": str(self.later_active.protocol.pk),
                "name": "Later Active",
                "purpose": "Newer start",
                "status": "active",
                "supplement_count": 2,
                "version": {
                    "id": str(self.later_active.id),
                    "version_number": 1,
                    "starts_on": self.later_active.starts_on.isoformat(),
                    "ends_on": self.later_active.ends_on.isoformat(),
                },
                "supplements": [
                    {
                        "id": str(self.later_magnesium.id),
                        "supplement": {
                            "id": str(self.later_magnesium.supplement_id),
                            "product_name": "Magnesium",
                            "brand_name": self.later_magnesium.supplement.brand.name,
                            "form": "capsule",
                        },
                        "dosage": "1 capsule",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_breakfast",
                        "duration": "90 days",
                        "instructions": "Take with food.",
                        "rationale": "Low vitamin D.",
                    },
                    {
                        "id": str(self.later_vitamin.id),
                        "supplement": {
                            "id": str(self.later_vitamin.supplement_id),
                            "product_name": "Vitamin D3",
                            "brand_name": self.later_vitamin.supplement.brand.name,
                            "form": "capsule",
                        },
                        "dosage": "1 capsule",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_breakfast",
                        "duration": "90 days",
                        "instructions": "Take with food.",
                        "rationale": "Low vitamin D.",
                    },
                ],
            },
        )
        self.assertEqual(data["active"][1]["supplements"], [])
        self.assertEqual([row["name"] for row in data["scheduled"]], ["Coming"])
        self.assertEqual([row["name"] for row in data["cancelled"]], ["Stopped"])
        self.assertEqual([row["name"] for row in data["expired"]], ["Finished"])
        self.assertNotIn("draft", data)

    def test_empty_plan_returns_zeros(self):
        empty = CustomerProfile.objects.create(
            customer=self.profile.customer,
            first_name="Kid",
            last_name="Shah",
            is_main=False,
        )
        response = self.protocols(self.customer, str(empty.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"],
            {
                "summary": {
                    "active": 0,
                    "scheduled": 0,
                    "draft": 0,
                    "cancelled": 0,
                    "expired": 0,
                },
                "active": [],
                "scheduled": [],
                "cancelled": [],
                "expired": [],
            },
        )

    def test_missing_header_is_not_found(self):
        response = self.protocols(self.customer)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_is_forbidden(self):
        response = self.protocols(self.admin, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PlanSupplementChangeListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_profile("plan-changes@example.com", "Ava", "Shah")
        self.customer = self.profile.customer.user
        UserAccount.objects.create(
            user=self.customer,
            account_type=UserType.CUSTOMER,
        )
        self.admin = create_staff_user("plan-changes-admin@example.com", UserType.ADMIN)
        today = timezone.localdate()
        self.fish = create_supplement(self.admin, name="Fish Oil", sku="CHANGE-FISH")
        self.fish.form = SupplementForm.SOFTGEL
        self.fish.save(update_fields=["form", "updated_at"])
        self.algae = create_supplement(
            self.admin,
            name="Algae Omega-3",
            sku="CHANGE-ALGAE",
        )
        self.algae.form = SupplementForm.SOFTGEL
        self.algae.save(update_fields=["form", "updated_at"])
        self.vitamin = create_supplement(self.admin, name="Vitamin D3", sku="CHANGE-D3")
        self.magnesium = create_supplement(
            self.admin,
            name="Magnesium Glycinate",
            sku="CHANGE-MAG",
        )
        self.b12 = create_supplement(self.admin, name="Vitamin B12", sku="CHANGE-B12")
        previous = ProtocolVersion.objects.create(
            protocol=Protocol.objects.create(
                customer_profile=self.profile,
                name="Zulu Active",
                purpose="Live",
            ),
            version_number=1,
            status=ProtocolVersionStatus.SUPERSEDED,
            starts_on=today - timedelta(days=40),
            ends_on=today - timedelta(days=1),
        )
        self.protocol = previous.protocol
        make_plan_item(previous, self.fish, timing=ProtocolItemTiming.WITH_LUNCH)
        make_plan_item(previous, self.vitamin, dosage="1 capsule")
        make_plan_item(previous, self.b12, rationale="B12 gap.")
        self.active = ProtocolVersion.objects.create(
            protocol=self.protocol,
            version_number=2,
            status=ProtocolVersionStatus.ACTIVE,
            starts_on=today - timedelta(days=1),
            ends_on=today + timedelta(days=30),
            supersedes=previous,
        )
        self.protocol.current_version = self.active
        self.protocol.save(update_fields=["current_version", "updated_at"])
        make_plan_item(
            self.active,
            self.algae,
            dosage="2 softgels",
            timing=ProtocolItemTiming.WITH_LUNCH,
            instructions="Take with the largest meal.",
            rationale="Vegan omega-3.",
        )
        make_plan_item(
            self.active,
            self.vitamin,
            dosage="2 capsules",
            duration="120 days",
            rationale="Still low on the repeat panel.",
        )
        make_plan_item(
            self.active,
            self.magnesium,
            dosage="2 capsules",
            timing=ProtocolItemTiming.AFTER_DINNER,
            instructions="Take in the evening.",
            rationale="Sleep support.",
        )
        ProtocolEvent.objects.create(
            customer_profile=self.profile,
            protocol=self.protocol,
            protocol_version=self.active,
            action=ProtocolEventAction.SUPPLEMENT_REPLACED,
            before={"supplement_id": str(self.fish.id)},
            after={"supplement_id": str(self.algae.id)},
        )
        scheduled_protocol = Protocol.objects.create(
            customer_profile=self.profile,
            name="Alpha Scheduled",
            purpose="Next",
        )
        ProtocolVersion.objects.create(
            protocol=scheduled_protocol,
            version_number=1,
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on=today + timedelta(days=7),
            ends_on=today + timedelta(days=40),
        )
        publish_current_version(
            self.profile,
            status=ProtocolVersionStatus.DRAFT,
            name="Draft Only",
            purpose="Hidden",
        )
        both = Protocol.objects.create(
            customer_profile=self.profile,
            name="Both Live",
            purpose="Prefer active",
        )
        ProtocolVersion.objects.create(
            protocol=both,
            version_number=2,
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on=today + timedelta(days=3),
        )
        ProtocolVersion.objects.create(
            protocol=both,
            version_number=1,
            status=ProtocolVersionStatus.ACTIVE,
            starts_on=today - timedelta(days=2),
        )

    def changes(self, user, profile_id="omit"):
        request = customer_plan_get(
            self.factory,
            user,
            "/supplementation/plan/supplement-changes/",
            profile_id,
        )
        return PlanSupplementChangeListView.as_view()(request)

    def test_customer_receives_diffs_for_live_protocols(self):
        response = self.changes(self.customer, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Supplement changes retrieved successfully.",
        )
        rows = response.data["data"]
        self.assertEqual(
            [(row["name"], row["status"]) for row in rows],
            [
                ("Both Live", "active"),
                ("Zulu Active", "active"),
                ("Alpha Scheduled", "scheduled"),
            ],
        )
        zulu = rows[1]
        self.assertEqual(
            zulu["changes"]["modified"],
            [
                {
                    "supplement": {
                        "id": str(self.vitamin.id),
                        "product_name": "Vitamin D3",
                        "brand_name": self.vitamin.brand.name,
                        "form": "capsule",
                    },
                    "before": {
                        "dosage": "1 capsule",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_breakfast",
                        "instructions": "Take with food.",
                        "rationale": "Low vitamin D.",
                    },
                    "after": {
                        "dosage": "2 capsules",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_breakfast",
                        "instructions": "Take with food.",
                        "rationale": "Still low on the repeat panel.",
                    },
                }
            ],
        )
        self.assertEqual(
            zulu["changes"]["replaced"],
            [
                {
                    "before": {
                        "supplement": {
                            "id": str(self.fish.id),
                            "product_name": "Fish Oil",
                            "brand_name": self.fish.brand.name,
                            "form": "softgel",
                        },
                        "dosage": "1 capsule",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_lunch",
                        "instructions": "Take with food.",
                        "rationale": "Low vitamin D.",
                    },
                    "after": {
                        "supplement": {
                            "id": str(self.algae.id),
                            "product_name": "Algae Omega-3",
                            "brand_name": self.algae.brand.name,
                            "form": "softgel",
                        },
                        "dosage": "2 softgels",
                        "frequency": "daily",
                        "custom_frequency": None,
                        "timing": "with_lunch",
                        "instructions": "Take with the largest meal.",
                        "rationale": "Vegan omega-3.",
                    },
                }
            ],
        )
        self.assertEqual(
            zulu["changes"]["added"][0]["supplement"]["product_name"],
            "Magnesium Glycinate",
        )
        self.assertEqual(
            zulu["changes"]["removed"][0]["supplement"]["product_name"],
            "Vitamin B12",
        )
        self.assertEqual(
            rows[2]["changes"],
            {"modified": [], "replaced": [], "added": [], "removed": []},
        )

    def test_empty_plan_returns_an_empty_list(self):
        empty = CustomerProfile.objects.create(
            customer=self.profile.customer,
            first_name="Kid",
            last_name="Shah",
            is_main=False,
        )
        response = self.changes(self.customer, str(empty.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], [])

    def test_missing_header_is_not_found(self):
        response = self.changes(self.customer)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_is_forbidden(self):
        response = self.changes(self.admin, str(self.profile.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

