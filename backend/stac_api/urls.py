from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

app_name = "stac_api"

# Passed to the schema view below so schema generation only ever
# traverses these routes.
api_urlpatterns = [
    path("", views.StacLandingPageView.as_view(), name="landing-page"),
    path("conformance/", views.StacConformanceView.as_view(), name="conformance"),
    path("search/", views.StacSearchView.as_view(), name="search"),
    path("collections/", views.StacCollectionListView.as_view(), name="collection-list"),
    path("collections/<str:name>/", views.StacCollectionDetailView.as_view(), name="collection-detail"),
    path("collections/<str:name>/items/", views.StacItemListView.as_view(), name="item-list"),
    path(
        "collections/<str:name>/items/<str:item_id>/",
        views.StacItemDetailView.as_view(),
        name="item-detail",
    ),
]

urlpatterns = api_urlpatterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(
            patterns=api_urlpatterns,
            custom_settings={
                "TITLE": "GeoQuery STAC API",
                "DESCRIPTION": (
                    "STAC (SpatioTemporal Asset Catalog) discovery API for GeoQuery "
                    "datasets and boundaries. Read-only, fully open, no authentication."
                ),
                "VERSION": "1.0.0",
            },
        ),
        name="schema",
    ),
    path("docs/", SpectacularSwaggerView.as_view(url_name="stac_api:schema"), name="docs"),
]
