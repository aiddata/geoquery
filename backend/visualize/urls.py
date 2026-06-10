from django.urls import path

from . import views

app_name = "visualize"

urlpatterns = [
    path(
        "request/<uuid:id>/",
        views.RequestVisualizationDataView.as_view(),
        name="request-data",
    ),
    path(
        "explore/available/",
        views.ExploreAvailableView.as_view(),
        name="explore-available",
    ),
    path(
        "explore/",
        views.ExploreDataView.as_view(),
        name="explore-data",
    ),
]
