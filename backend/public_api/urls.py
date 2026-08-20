from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

app_name = "public_api"

# Passed to the schema view below so OpenAPI generation only ever
# traverses these routes, never the internal /api/* endpoints used by
# the frontend.
#
# NOTE: datasets/categories/ and datasets/coverage/ must be listed
# before datasets/<str:name>/, otherwise Django would match "categories"
# or "coverage" as a dataset name first. Same reason boundaries/autocomplete/
# and boundaries/presets/ must be listed before boundaries/<str:name>/.
api_urlpatterns = [
    path("datasets/", views.PublicDatasetListView.as_view(), name="dataset-list"),
    path(
        "datasets/categories/",
        views.PublicDatasetCategoryView.as_view(),
        name="dataset-categories",
    ),
    path(
        "datasets/coverage/",
        views.PublicDatasetCoverageView.as_view(),
        name="dataset-coverage",
    ),
    path("datasets/<str:name>/", views.PublicDatasetDetailView.as_view(), name="dataset-detail"),
    path(
        "boundaries/autocomplete/",
        views.PublicBoundaryAutocompleteView.as_view(),
        name="boundary-autocomplete",
    ),
    path(
        "boundaries/presets/",
        views.PublicBoundaryPresetsView.as_view(),
        name="boundary-presets",
    ),
    path("boundaries/<str:name>/", views.PublicBoundaryDetailView.as_view(), name="boundary-detail"),
]

urlpatterns = api_urlpatterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(patterns=api_urlpatterns),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="public_api:schema"),
        name="docs",
    ),
]
