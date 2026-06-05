from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestView.as_view(), name="request-list-create"),
    path("requests/<uuid:pk>/", views.RequestDetailView.as_view(), name="request-detail"),
    path("request-token/", views.RequestTokenView.as_view(), name="request-token"),
    path("history/<str:token>/", views.RequestHistoryView.as_view(), name="request-history"),
]
