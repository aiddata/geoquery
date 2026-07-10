from django.urls import path

from . import views

urlpatterns = [
    path("", views.DatasetListView.as_view(), name="dataset-list"),
    path("coverage/", views.DatasetCoverageView.as_view(), name="dataset-coverage"),
    path("categories/", views.DatasetCategoryView.as_view(), name="dataset-categories"),
    path("<str:name>/", views.DatasetDetailView.as_view(), name="dataset-detail"),
]
