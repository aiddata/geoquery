from django.urls import path

from . import views

app_name = "stac_api"

# Passed to the schema view (added in a later task) so schema generation
# only ever traverses these routes.
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

urlpatterns = api_urlpatterns
