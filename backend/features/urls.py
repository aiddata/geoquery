from django.urls import path

from . import views

app_name = "features"

urlpatterns = [
    path(
        "autocomplete/",
        views.FeatureCollectionAutocompleteView.as_view(),
        name="feature-collection-autocomplete",
    ),
    path(
        "ids/",
        views.FeatureIdsView.as_view(),
        name="feature-ids",
    ),
    path(
        "presets/",
        views.BoundaryPresetsView.as_view(),
        name="boundary-presets",
    ),
    path(
        "tiles/<str:fc_name>/<int:z>/<int:x>/<int:y>.mvt",
        views.feature_collection_vector_tiles,
        name="feature-collection-tiles",
    ),
]
