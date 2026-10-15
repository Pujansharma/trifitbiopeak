"""ROOK appends /client_uuid/{uuid}/user_id/{id} to redirect_url."""
from django.urls import path
from wearables.views import RookOAuthCallbackView

urlpatterns = [
    path("<str:state_token>/client_uuid/<str:client_uuid>/user_id/<str:rook_user_id>",
         RookOAuthCallbackView.as_view(), name="rook-oauth-return"),
    path("<str:state_token>/client_uuid/<str:client_uuid>/user_id/<str:rook_user_id>/",
         RookOAuthCallbackView.as_view(), name="rook-oauth-return-trailing-slash"),
]
