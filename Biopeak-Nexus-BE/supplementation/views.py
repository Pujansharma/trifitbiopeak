import re

from django.db.models import (
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, Concat, Greatest
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound

from accounts.associates.models import AssociateCenterAssignment
from accounts.associates.utils.roles import active_role_links_prefetch
from accounts.customers.models import CustomerProfile
from accounts.utils.permissions import IsAdminUser, IsAssociateUser, IsCustomerUser
from core.utils.exceptions import get_object_or_404
from core.utils.views import (
    BaseCreateAPIView,
    BaseGenericAPIView,
    BaseListAPIView,
    BaseRetrieveAPIView,
)
from supplementation.models import (
    AiRecommendation,
    AiRecommendationItem,
    ClientConstraint,
    Protocol,
    ProtocolAiJob,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
    Supplement,
)
from supplementation.serializers import (
    AiRecommendationDetailSerializer,
    AiRecommendationDraftSerializer,
    AiRecommendationItemAcceptSerializer,
    AiRecommendationItemModifySerializer,
    AiRecommendationItemRejectSerializer,
    AiRecommendationListSerializer,
    PlanProtocolsSerializer,
    PlanRoutineSerializer,
    PlanSummarySerializer,
    PlanSupplementChangeSerializer,
    ProtocolAiQueueSerializer,
    ProtocolCreateSerializer,
    ProtocolCurrentVersionSerializer,
    ProtocolDetailSerializer,
    ProtocolItemDeleteSerializer,
    ProtocolItemReplaceSerializer,
    ProtocolItemSerializer,
    ProtocolItemUpdateSerializer,
    ProtocolVersionApproveSerializer,
    ProtocolVersionCancelSerializer,
    ProtocolVersionCreateSerializer,
    ProtocolVersionExtendSerializer,
    ProtocolVersionPublishSerializer,
    SupplementationProfileDetailSerializer,
    SupplementationProfileEventSerializer,
    SupplementationProfileListSerializer,
    SupplementCreateSerializer,
    SupplementDetailSerializer,
    SupplementMasterListSerializer,
)
from supplementation.utils.constants import (
    OPEN_AI_RECOMMENDATION_DECISIONS,
    AiRecommendationItemDecision,
    AiRecommendationListStatus,
    ProtocolAiJobStatus,
    ProtocolEventAction,
    ProtocolVersionStatus,
    SupplementForm,
)
from supplementation.utils.plan import (
    plan_protocols,
    plan_routine,
    plan_supplement_changes,
)
from supplementation.utils.protocols import protocol_status_counts
from supplementation.utils.version_status import (
    LIVE_PROTOCOL_VERSION_STATUSES,
    listed_protocol_versions,
)

CENTER_QUERY_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

IN_FLIGHT_PROTOCOL_AI_JOBS = Q(
    status__in=[ProtocolAiJobStatus.PENDING, ProtocolAiJobStatus.PROCESSING],
)


def latest_related_updated_at(rows):
    return Subquery(rows.order_by("-updated_at").values("updated_at")[:1])


def recommendation_item_count(item_filter: Q | None = None):
    item_rows = AiRecommendationItem.objects.filter(recommendation__job=OuterRef("pk"))
    if item_filter is not None:
        item_rows = item_rows.filter(item_filter)
    counted_items = (
        item_rows.order_by()
        .values("recommendation__job")
        .annotate(item_count=Count("pk"))
        .values("item_count")
    )
    return Coalesce(Subquery(counted_items, output_field=IntegerField()), Value(0))


RECOMMENDATION_LIST_FILTERS = {
    AiRecommendationListStatus.PROCESSING: IN_FLIGHT_PROTOCOL_AI_JOBS,
    AiRecommendationListStatus.FAILED: Q(status=ProtocolAiJobStatus.FAILED),
    AiRecommendationListStatus.PENDING: IN_FLIGHT_PROTOCOL_AI_JOBS
    | Q(status=ProtocolAiJobStatus.COMPLETED, open_count__gt=0),
    AiRecommendationListStatus.COMPLETED: Q(
        status=ProtocolAiJobStatus.COMPLETED,
        open_count=0,
    ),
}


class SupplementationProfileListViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_supplementation_profile_list_queryset(self, *, search: str, center: str | None):
        queryset = CustomerProfile.objects.filter(is_active=True, **self.filter_kwargs)
        if center:
            queryset = queryset.filter(
                center_assignments__center=center,
                center_assignments__is_active=True,
            )
        if search:
            queryset = queryset.annotate(
                profile_name=Concat(
                    Coalesce("first_name", Value("")),
                    Value(" "),
                    Coalesce("last_name", Value("")),
                )
            ).filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(profile_name__icontains=search)
            )
        return (
            queryset.annotate(
                constraint_updated_at=latest_related_updated_at(
                    ClientConstraint.objects.filter(customer_profile=OuterRef("pk"))
                ),
                version_updated_at=latest_related_updated_at(
                    ProtocolVersion.objects.filter(
                        protocol__customer_profile=OuterRef("pk"),
                    )
                ),
            )
            .annotate(
                plan_updated_at=Coalesce(
                    Greatest("constraint_updated_at", "version_updated_at"),
                    "constraint_updated_at",
                    "version_updated_at",
                )
            )
            .prefetch_related(
                Prefetch(
                    "supplement_constraints",
                    queryset=ClientConstraint.objects.order_by("name", "created_at"),
                ),
                Prefetch(
                    "supplement_protocols",
                    queryset=Protocol.objects.select_related("current_version"),
                ),
            )
            .order_by(F("plan_updated_at").desc(nulls_last=True), "-created_at")
            .distinct()
        )


class SupplementationProfileDetailViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_supplementation_profile_detail_queryset(self):
        return (
            CustomerProfile.objects.filter(is_active=True, **self.filter_kwargs)
            .select_related("customer__user")
            .annotate(protocol_count=Count("supplement_protocols"))
            .prefetch_related(
                Prefetch(
                    "supplement_constraints",
                    queryset=ClientConstraint.objects.order_by("name", "created_at"),
                ),
            )
        )


class ProtocolReadViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_protocol_version_queryset(self):
        return ProtocolVersion.objects.annotate(supplement_count=Count("items"))

    def get_protocol_queryset(self):
        return Protocol.objects.filter(**self.filter_kwargs).prefetch_related(
            Prefetch(
                "versions",
                queryset=self.get_protocol_version_queryset().order_by(
                    "version_number"
                ),
            )
        )


class ProtocolEventViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_protocol_event_queryset(self, *, action: str | None):
        queryset = (
            ProtocolEvent.objects.filter(**self.filter_kwargs)
            .select_related(
                "protocol",
                "protocol_version",
                "actor__associate",
            )
            .prefetch_related(
                Prefetch(
                    "actor__associate__center_assignments",
                    queryset=AssociateCenterAssignment.objects.filter(
                        is_active=True,
                    ).prefetch_related(active_role_links_prefetch()),
                )
            )
        )
        if action:
            queryset = queryset.filter(action=action)
        return queryset.order_by("-created_at", "-id")


class PlanReadViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_profile_plan_protocols(self, profile):
        return Protocol.objects.filter(
            customer_profile=profile,
            **self.filter_kwargs,
        ).select_related("current_version")

    def get_active_routine_items(self, profile):
        today = timezone.localdate()
        return (
            ProtocolItem.objects.filter(
                version__status=ProtocolVersionStatus.ACTIVE,
                version__is_active=True,
                version__protocol__customer_profile=profile,
                version__protocol__is_active=True,
                **self.filter_kwargs,
            )
            .filter(Q(version__ends_on__isnull=True) | Q(version__ends_on__gte=today))
            .select_related("supplement__brand", "version")
            .order_by("supplement__product_name", "id")
        )

    def get_plan_protocol_item_queryset(self):
        return (
            ProtocolItem.objects.select_related("supplement__brand")
            .order_by("supplement__product_name", "id")
        )

    def get_profile_plan_protocol_rows(self, profile):
        current_versions = (
            ProtocolVersion.objects.filter(protocol__current_version=F("pk"))
            .annotate(supplement_count=Count("items"))
            .prefetch_related(
                Prefetch("items", queryset=self.get_plan_protocol_item_queryset())
            )
        )
        return (
            Protocol.objects.filter(customer_profile=profile, is_active=True)
            .select_related("current_version")
            .annotate(
                draft_count=Count(
                    "versions",
                    filter=Q(
                        versions__is_active=True,
                        versions__status=ProtocolVersionStatus.DRAFT,
                    ),
                )
            )
            .prefetch_related(Prefetch("versions", queryset=current_versions))
        )

    def get_shown_plan_versions(self, profile):
        live_versions = ProtocolVersion.objects.filter(
            protocol__customer_profile=profile,
            protocol__is_active=True,
            is_active=True,
            status__in=LIVE_PROTOCOL_VERSION_STATUSES,
        )
        return (
            ProtocolVersion.objects.filter(
                Q(pk__in=live_versions.values("pk"))
                | Q(pk__in=live_versions.values("supersedes"))
            )
            .select_related("supersedes")
            .prefetch_related(
                Prefetch("items", queryset=self.get_plan_protocol_item_queryset()),
                Prefetch(
                    "events",
                    queryset=ProtocolEvent.objects.filter(
                        action=ProtocolEventAction.SUPPLEMENT_REPLACED,
                    ).order_by("created_at", "id"),
                    to_attr="replace_events",
                ),
            )
        )

    def get_profile_live_protocols(self, profile):
        return (
            Protocol.objects.filter(
                customer_profile=profile,
                is_active=True,
                versions__is_active=True,
                versions__status__in=LIVE_PROTOCOL_VERSION_STATUSES,
            )
            .distinct()
            .prefetch_related(
                Prefetch("versions", queryset=self.get_shown_plan_versions(profile))
            )
        )


class AiRecommendationReadViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_ai_recommendation_queryset(self):
        return (
            AiRecommendation.objects.filter(**self.filter_kwargs)
            .select_related("customer_profile")
            .annotate(
                total=Count("items"),
                accepted=Count(
                    "items",
                    filter=Q(items__decision=AiRecommendationItemDecision.ACCEPTED),
                ),
                modified=Count(
                    "items",
                    filter=Q(items__decision=AiRecommendationItemDecision.MODIFIED),
                ),
                rejected=Count(
                    "items",
                    filter=Q(items__decision=AiRecommendationItemDecision.REJECTED),
                ),
                pending_count=Count(
                    "items",
                    filter=Q(items__decision=AiRecommendationItemDecision.PENDING),
                ),
                open_count=Count(
                    "items",
                    filter=Q(items__decision__in=OPEN_AI_RECOMMENDATION_DECISIONS),
                ),
            )
        )

    def get_ai_recommendation_list_queryset(self, *, search: str, recommendation_status: str):
        queryset = ProtocolAiJob.objects.filter(**self.filter_kwargs).select_related(
            "customer_profile"
        ).annotate(
            recommendation_pk=F("recommendation__id"),
            recommendation_model=F("recommendation__model"),
            total=recommendation_item_count(),
            accepted=recommendation_item_count(
                Q(decision=AiRecommendationItemDecision.ACCEPTED),
            ),
            modified=recommendation_item_count(
                Q(decision=AiRecommendationItemDecision.MODIFIED),
            ),
            rejected=recommendation_item_count(
                Q(decision=AiRecommendationItemDecision.REJECTED),
            ),
            open_count=recommendation_item_count(
                Q(decision__in=OPEN_AI_RECOMMENDATION_DECISIONS),
            ),
        )
        status_filter = RECOMMENDATION_LIST_FILTERS.get(recommendation_status)
        if status_filter is not None:
            queryset = queryset.filter(status_filter)
        if search:
            queryset = queryset.annotate(
                profile_name=Concat(
                    Coalesce("customer_profile__first_name", Value("")),
                    Value(" "),
                    Coalesce("customer_profile__last_name", Value("")),
                )
            ).filter(
                Q(customer_profile__first_name__icontains=search)
                | Q(customer_profile__last_name__icontains=search)
                | Q(profile_name__icontains=search)
                | Q(name__icontains=search)
            )
        return queryset.order_by("-created_at", "-id")

    def get_ai_recommendation_detail_queryset(self):
        return self.get_ai_recommendation_queryset().prefetch_related(
            Prefetch(
                "items",
                queryset=AiRecommendationItem.objects.select_related("supplement__brand"),
            )
        )


class AiRecommendationItemViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_recommendation_item_queryset(self):
        return AiRecommendationItem.objects.filter(**self.filter_kwargs).select_related(
            "supplement__brand",
            "recommendation",
        )

    def get_recommendation_item(self):
        return get_object_or_404(
            self.get_recommendation_item_queryset(),
            "AI recommendation item not found.",
            pk=self.kwargs["pk"],
        )


class SupplementMasterListView(BaseListAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementMasterListSerializer
    list_success_message = "Supplements retrieved successfully."

    def get_queryset(self):
        filter_kwargs = {}
        search = Q()
        search_query = self.request.query_params.get("search", "").strip()
        form_query = self.request.query_params.get("form", "").strip()
        active_query = self.request.query_params.get("active")

        if form_query:
            if form_query not in SupplementForm.values:
                self.raise_bad_request("Invalid form.")
            filter_kwargs["form"] = form_query

        if active_query in ["0", "1"]:
            filter_kwargs["is_active"] = bool(int(active_query))

        if search_query:
            search |= Q(product_name__icontains=search_query)
            search |= Q(brand__name__icontains=search_query)

        return (
            Supplement.objects.select_related("brand")
            .prefetch_related("allergens")
            .filter(search, **filter_kwargs)
        )


class SupplementMasterDetailView(BaseRetrieveAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementDetailSerializer
    retrieve_success_message = "Supplement retrieved successfully."

    def get_queryset(self):
        return Supplement.objects.select_related("brand").prefetch_related(
            "active_ingredients",
            "allergens",
        )


class SupplementationProfileListView(
    BaseListAPIView,
    SupplementationProfileListViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementationProfileListSerializer
    list_success_message = "Supplementation profiles retrieved successfully."

    def get_queryset(self):
        search = self.request.query_params.get("search", "").strip()
        center = self.request.query_params.get("center", "").strip()
        if center and CENTER_QUERY_PATTERN.fullmatch(center) is None:
            self.raise_bad_request("Invalid center.")
        return self.get_supplementation_profile_list_queryset(
            search=search,
            center=center or None,
        )


class SupplementationProfileDetailView(
    BaseRetrieveAPIView,
    SupplementationProfileDetailViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementationProfileDetailSerializer
    lookup_url_kwarg = "profile_id"
    retrieve_success_message = "Supplementation profile retrieved successfully."

    def get_queryset(self):
        return self.get_supplementation_profile_detail_queryset()


class SupplementationProfileProtocolListView(BaseListAPIView, ProtocolReadViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolDetailSerializer
    list_success_message = "Protocols retrieved successfully."

    def get_queryset(self):
        profile_id = self.kwargs["profile_id"]
        get_object_or_404(
            CustomerProfile.objects.filter(is_active=True),
            pk=profile_id,
        )
        return self.get_protocol_queryset().filter(customer_profile=profile_id)

    def post(self, request, *args, **kwargs):
        profile = get_object_or_404(
            CustomerProfile.objects.filter(is_active=True),
            pk=self.kwargs["profile_id"],
        )
        serializer = ProtocolCreateSerializer(
            data=request.data,
            context={"request": request, "customer_profile": profile},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        created = (
            self.get_protocol_queryset()
            .filter(pk=serializer.instance.pk)
            .first()
        )
        if created is None:
            raise NotFound("Protocol not found.")
        return self.send_response(
            "Protocol created.",
            ProtocolDetailSerializer(created).data,
            status=status.HTTP_201_CREATED,
        )


class SupplementationProfileCurrentVersionListView(
    BaseListAPIView,
    ProtocolReadViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolCurrentVersionSerializer
    pagination_class = None
    list_success_message = "Current protocol versions retrieved successfully."

    def get_queryset(self):
        profile_id = self.kwargs["profile_id"]
        get_object_or_404(
            CustomerProfile.objects.filter(is_active=True),
            pk=profile_id,
        )
        listed_versions = listed_protocol_versions()
        chosen_version_number = Subquery(
            listed_versions.filter(protocol=OuterRef("protocol"))
            .order_by("-version_number")
            .values("version_number")[:1]
        )
        return (
            Protocol.objects.filter(customer_profile=profile_id)
            .filter(Exists(listed_versions.filter(protocol=OuterRef("pk"))))
            .prefetch_related(
                Prefetch(
                    "versions",
                    queryset=self.get_protocol_version_queryset().filter(
                        version_number=chosen_version_number,
                    ),
                )
            )
            .order_by("-created_at", "-id")
        )


class ProtocolVersionCreateView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolVersionCreateSerializer

    def post(self, request, *args, **kwargs):
        protocol = get_object_or_404(Protocol, pk=self.kwargs["pk"])
        serializer = ProtocolVersionCreateSerializer(
            data=request.data,
            context={"request": request, "protocol": protocol},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "Protocol version created.",
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class ProtocolDetailView(BaseRetrieveAPIView, ProtocolReadViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolDetailSerializer
    retrieve_success_message = "Protocol retrieved successfully."

    def get_queryset(self):
        return self.get_protocol_queryset()


class ProtocolEventListView(BaseListAPIView, ProtocolEventViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementationProfileEventSerializer
    list_success_message = "Protocol events retrieved successfully."

    def get_queryset(self):
        protocol_id = self.kwargs["pk"]
        get_object_or_404(Protocol, pk=protocol_id)
        action = self.request.query_params.get("action", "").strip()
        if action and action not in ProtocolEventAction.values:
            self.raise_bad_request("Invalid action.")
        self.filter_kwargs = {
            "protocol": protocol_id,
            "protocol_version__isnull": False,
        }
        return self.get_protocol_event_queryset(action=action or None)


class ProtocolVersionEventListView(BaseListAPIView, ProtocolEventViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementationProfileEventSerializer
    list_success_message = "Protocol version events retrieved successfully."

    def get_queryset(self):
        version_id = self.kwargs["pk"]
        get_object_or_404(
            ProtocolVersion,
            "Protocol version not found.",
            pk=version_id,
        )
        action = self.request.query_params.get("action", "").strip()
        if action and action not in ProtocolEventAction.values:
            self.raise_bad_request("Invalid action.")
        self.filter_kwargs = {"protocol_version": version_id}
        return self.get_protocol_event_queryset(action=action or None)


class ProtocolVersionItemListView(BaseListAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolItemSerializer
    pagination_class = None
    list_success_message = "Protocol supplements retrieved."

    def get_version(self):
        return get_object_or_404(
            ProtocolVersion.objects.select_related("protocol__customer_profile"),
            "Protocol version not found.",
            pk=self.kwargs["pk"],
        )

    def get_queryset(self):
        version = self.get_version()
        return version.items.select_related("supplement__brand").order_by(
            "created_at",
            "id",
        )

    def post(self, request, *args, **kwargs):
        version = self.get_version()
        serializer = ProtocolItemSerializer(
            data=request.data,
            context={"request": request, "version": version},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "Supplement added to protocol version.",
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


def get_protocol_item(item_id):
    return get_object_or_404(
        ProtocolItem.objects.select_related(
            "version__protocol__customer_profile",
            "supplement__brand",
        ),
        "Protocol supplement not found.",
        pk=item_id,
    )


class ProtocolItemDetailView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolItemUpdateSerializer

    def patch(self, request, *args, **kwargs):
        item = get_protocol_item(self.kwargs["pk"])
        serializer = ProtocolItemUpdateSerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "Supplement updated on protocol version.",
            serializer.data,
        )

    def delete(self, request, *args, **kwargs):
        item = get_protocol_item(self.kwargs["pk"])
        serializer = ProtocolItemDeleteSerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Supplement removed from protocol version.")


class ProtocolItemReplaceView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolItemReplaceSerializer

    def post(self, request, *args, **kwargs):
        item = get_protocol_item(self.kwargs["pk"])
        serializer = ProtocolItemReplaceSerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "Supplement replaced on protocol version.",
            serializer.data,
        )


def customer_plan_profile(request):
    profile_id = request.headers.get("X-Customer-Profile-ID", "").strip()
    if CENTER_QUERY_PATTERN.fullmatch(profile_id) is None:
        raise NotFound("Customer profile not found.")
    return get_object_or_404(
        CustomerProfile.objects.filter(
            customer__user=request.user,
            is_active=True,
        ),
        "Customer profile not found.",
        pk=profile_id,
    )


class PlanSummaryView(PlanReadViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = PlanSummarySerializer

    def get(self, request, *args, **kwargs):
        profile = customer_plan_profile(request)
        serializer = self.get_serializer(
            protocol_status_counts(
                self.get_profile_plan_protocols(profile),
                timezone.localdate(),
            )
        )
        return self.send_response(
            "Protocol summary retrieved successfully.",
            serializer.data,
        )


class PlanRoutineView(PlanReadViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = PlanRoutineSerializer

    def get(self, request, *args, **kwargs):
        profile = customer_plan_profile(request)
        serializer = self.get_serializer(
            plan_routine(self.get_active_routine_items(profile))
        )
        return self.send_response(
            "Active supplements retrieved successfully.",
            serializer.data,
        )


class PlanProtocolListView(PlanReadViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = PlanProtocolsSerializer

    def get(self, request, *args, **kwargs):
        profile = customer_plan_profile(request)
        serializer = self.get_serializer(
            plan_protocols(self.get_profile_plan_protocol_rows(profile))
        )
        return self.send_response(
            "Protocols retrieved successfully.",
            serializer.data,
        )


class PlanSupplementChangeListView(PlanReadViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = PlanSupplementChangeSerializer

    def get(self, request, *args, **kwargs):
        profile = customer_plan_profile(request)
        serializer = self.get_serializer(
            plan_supplement_changes(self.get_profile_live_protocols(profile)),
            many=True,
        )
        return self.send_response(
            "Supplement changes retrieved successfully.",
            serializer.data,
        )


class ProtocolVersionApproveView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolVersionApproveSerializer

    def post(self, request, *args, **kwargs):
        version = get_object_or_404(
            ProtocolVersion.objects.select_related("protocol__customer_profile"),
            "Protocol version not found.",
            pk=self.kwargs["pk"],
        )
        serializer = ProtocolVersionApproveSerializer(
            version,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Protocol version approved.")


class ProtocolVersionPublishView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolVersionPublishSerializer

    def post(self, request, *args, **kwargs):
        version = get_object_or_404(
            ProtocolVersion.objects.select_related(
                "protocol__customer_profile",
                "protocol__current_version",
            ),
            "Protocol version not found.",
            pk=self.kwargs["pk"],
        )
        serializer = ProtocolVersionPublishSerializer(
            version,
            data={},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Protocol version published.")


class ProtocolVersionCancelView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolVersionCancelSerializer

    def post(self, request, *args, **kwargs):
        version = get_object_or_404(
            ProtocolVersion.objects.select_related("protocol__customer_profile"),
            "Protocol version not found.",
            pk=self.kwargs["pk"],
        )
        serializer = ProtocolVersionCancelSerializer(
            version,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Protocol version cancelled.")


class ProtocolVersionExtendView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolVersionExtendSerializer

    def patch(self, request, *args, **kwargs):
        version = get_object_or_404(
            ProtocolVersion.objects.select_related("protocol__customer_profile"),
            "Protocol version not found.",
            pk=self.kwargs["pk"],
        )
        serializer = ProtocolVersionExtendSerializer(
            version,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Protocol version extended.")


class SupplementationProfileEventListView(BaseListAPIView, ProtocolEventViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementationProfileEventSerializer
    list_success_message = "Supplementation events retrieved successfully."

    def get_queryset(self):
        profile_id = self.kwargs["profile_id"]
        get_object_or_404(
            CustomerProfile.objects.filter(is_active=True),
            pk=profile_id,
        )
        action = self.request.query_params.get("action", "").strip()
        if action and action not in ProtocolEventAction.values:
            self.raise_bad_request("Invalid action.")
        self.filter_kwargs = {"customer_profile": profile_id}
        return self.get_protocol_event_queryset(action=action or None)


class SupplementCreateView(BaseCreateAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = SupplementCreateSerializer
    create_success_message = "Supplement created successfully."

    def get_queryset(self):
        return Supplement.objects.select_related("brand").prefetch_related(
            "active_ingredients",
            "allergens",
        )


class ProtocolAiQueueView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = ProtocolAiQueueSerializer

    def post(self, request, profile_id):
        profile = get_object_or_404(
            CustomerProfile.objects.filter(is_active=True),
            "Customer profile not found.",
            pk=profile_id,
        )
        serializer = ProtocolAiQueueSerializer(
            data=request.data,
            context={"request": request, "customer_profile": profile},
        )
        serializer.is_valid(raise_exception=True)
        job = serializer.save()
        return self.send_response(
            "Protocol recommendation queued.",
            {"id": str(job.pk), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )


class AiRecommendationListView(BaseListAPIView, AiRecommendationReadViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationListSerializer
    list_success_message = "AI recommendations retrieved successfully."

    def get_queryset(self):
        recommendation_status = self.request.query_params.get(
            "recommendation_status",
            "",
        ).strip()
        if (
            recommendation_status
            and recommendation_status not in RECOMMENDATION_LIST_FILTERS
        ):
            self.raise_bad_request("Invalid recommendation_status.")
        search = self.request.query_params.get("search", "").strip()
        return self.get_ai_recommendation_list_queryset(
            search=search,
            recommendation_status=recommendation_status,
        )


class AiRecommendationDetailView(BaseRetrieveAPIView, AiRecommendationReadViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationDetailSerializer
    retrieve_success_message = "AI recommendation retrieved successfully."

    def get_queryset(self):
        return self.get_ai_recommendation_detail_queryset()

    def get_object(self):
        return get_object_or_404(
            self.get_queryset(),
            "AI recommendation not found.",
            pk=self.kwargs["pk"],
        )


class AiRecommendationDraftView(BaseGenericAPIView):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationDraftSerializer

    def post(self, request, pk):
        recommendation = get_object_or_404(
            AiRecommendation.objects,
            "AI recommendation not found.",
            pk=pk,
        )
        serializer = AiRecommendationDraftSerializer(
            recommendation,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "Protocol version created.",
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class AiRecommendationItemAcceptView(AiRecommendationItemViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationItemAcceptSerializer

    def post(self, request, pk):
        item = self.get_recommendation_item()
        serializer = AiRecommendationItemAcceptSerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "AI recommendation item accepted.",
            serializer.data,
        )


class AiRecommendationItemRejectView(AiRecommendationItemViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationItemRejectSerializer

    def post(self, request, pk):
        item = self.get_recommendation_item()
        serializer = AiRecommendationItemRejectSerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "AI recommendation item rejected.",
            serializer.data,
        )


class AiRecommendationItemModifyView(AiRecommendationItemViewMeta):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = AiRecommendationItemModifySerializer

    def patch(self, request, pk):
        item = self.get_recommendation_item()
        serializer = AiRecommendationItemModifySerializer(
            item,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(
            "AI recommendation item updated.",
            serializer.data,
        )
