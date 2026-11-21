from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.csrf_view, name="auth-csrf"),
    path("preferences/", views.PreferencesView.as_view(), name="auth-preferences"),
]
