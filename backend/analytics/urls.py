from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestView.as_view(), name="request-list-create"),
    path(
        "requests/<uuid:pk>/", views.RequestDetailView.as_view(), name="request-detail"
    ),
    path("request-token/", views.RequestTokenView.as_view(), name="request-token"),
    path("my-requests/", views.MyRequestsView.as_view(), name="my-requests"),
    path(
        "history/<str:token>/",
        views.RequestHistoryView.as_view(),
        name="request-history",
    ),
    # Legacy requests from the previous version of GeoQuery. Parallel to the
    # routes above rather than folded into them: the current payloads are bare
    # arrays shared with the MCP server, so adding a key would break it.
    path(
        "legacy-requests/",
        views.LegacyMyRequestsView.as_view(),
        name="legacy-my-requests",
    ),
    path(
        "legacy-requests/<str:pk>/",
        views.LegacyRequestDetailView.as_view(),
        name="legacy-request-detail",
    ),
    path(
        "legacy-history/<str:token>/",
        views.LegacyRequestHistoryView.as_view(),
        name="legacy-request-history",
    ),
]
