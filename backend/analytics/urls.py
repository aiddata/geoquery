from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestView.as_view(), name="request-list-create"),
    path("requests/<uuid:pk>/", views.RequestDetailView.as_view(), name="request-detail"),
]
