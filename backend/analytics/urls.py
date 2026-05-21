from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestView.as_view(), name="request-list-create"),
]
