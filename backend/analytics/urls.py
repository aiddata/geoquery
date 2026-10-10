from django.urls import path, re_path

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
    # re_path, not <str:pk>: a str converter matches anything, so a percent-
    # encoded NUL reached psycopg and raised DataError -- an uncaught 500 on
    # every scanner hit. Constraining to the ObjectId shape turns every
    # wrong-shape id into a resolver 404 before it can touch the database.
    # RequestDetailView is immune only because <uuid:pk> happens to validate.
    re_path(
        r"^legacy-requests/(?P<pk>[0-9a-fA-F]{24})/$",
        views.LegacyRequestDetailView.as_view(),
        name="legacy-request-detail",
    ),
    path(
        "legacy-history/<str:token>/",
        views.LegacyRequestHistoryView.as_view(),
        name="legacy-request-history",
    ),
]
