from django.urls import path

from . import views

app_name = "visualize"

urlpatterns = [
    path(
        "request/<uuid:id>/",
        views.RequestVisualizationDataView.as_view(),
        name="request-data",
    ),
]