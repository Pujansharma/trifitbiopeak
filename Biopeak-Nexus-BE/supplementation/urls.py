from django.urls import path

from supplementation import views

urlpatterns = [
    path("master/", views.SupplementMasterListView.as_view()),
    path("master/new-supplement/", views.SupplementCreateView.as_view()),
    path("master/<uuid:pk>/", views.SupplementMasterDetailView.as_view()),
    path("profiles/", views.SupplementationProfileListView.as_view()),
    path(
        "profiles/<uuid:profile_id>/",
        views.SupplementationProfileDetailView.as_view(),
    ),
    path(
        "profiles/<uuid:profile_id>/events/",
        views.SupplementationProfileEventListView.as_view(),
    ),
    path(
        "profiles/<uuid:profile_id>/protocols/current-versions/",
        views.SupplementationProfileCurrentVersionListView.as_view(),
    ),
    path(
        "profiles/<uuid:profile_id>/protocols/",
        views.SupplementationProfileProtocolListView.as_view(),
    ),
    path(
        "profiles/<uuid:profile_id>/protocols/ai/",
        views.ProtocolAiQueueView.as_view(),
    ),
    path(
        "ai-recommendations/",
        views.AiRecommendationListView.as_view(),
    ),
    path(
        "ai-recommendations/<uuid:pk>/",
        views.AiRecommendationDetailView.as_view(),
    ),
    path(
        "ai-recommendations/<uuid:pk>/draft/",
        views.AiRecommendationDraftView.as_view(),
    ),
    path(
        "ai-recommendation-items/<uuid:pk>/accept/",
        views.AiRecommendationItemAcceptView.as_view(),
    ),
    path(
        "ai-recommendation-items/<uuid:pk>/reject/",
        views.AiRecommendationItemRejectView.as_view(),
    ),
    path(
        "ai-recommendation-items/<uuid:pk>/",
        views.AiRecommendationItemModifyView.as_view(),
    ),
    path(
        "protocols/<uuid:pk>/versions/",
        views.ProtocolVersionCreateView.as_view(),
    ),
    path(
        "protocols/<uuid:pk>/events/",
        views.ProtocolEventListView.as_view(),
    ),
    path("protocols/<uuid:pk>/", views.ProtocolDetailView.as_view()),
    path(
        "protocol-versions/<uuid:pk>/events/",
        views.ProtocolVersionEventListView.as_view(),
    ),
    path(
        "protocol-versions/<uuid:pk>/items/",
        views.ProtocolVersionItemListView.as_view(),
    ),
    path(
        "protocol-items/<uuid:pk>/replace/",
        views.ProtocolItemReplaceView.as_view(),
    ),
    path(
        "protocol-items/<uuid:pk>/",
        views.ProtocolItemDetailView.as_view(),
    ),
    path(
        "protocol-versions/<uuid:pk>/approve/",
        views.ProtocolVersionApproveView.as_view(),
    ),
    path(
        "protocol-versions/<uuid:pk>/publish/",
        views.ProtocolVersionPublishView.as_view(),
    ),
    path(
        "protocol-versions/<uuid:pk>/cancel/",
        views.ProtocolVersionCancelView.as_view(),
    ),
    path(
        "protocol-versions/<uuid:pk>/extend/",
        views.ProtocolVersionExtendView.as_view(),
    ),
    path("plan/summary/", views.PlanSummaryView.as_view()),
    path("plan/routine/", views.PlanRoutineView.as_view()),
    path("plan/protocols/", views.PlanProtocolListView.as_view()),
    path("plan/supplement-changes/", views.PlanSupplementChangeListView.as_view()),
]
