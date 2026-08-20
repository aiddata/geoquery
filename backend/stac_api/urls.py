from django.urls import path

from . import views

app_name = "stac_api"

# Passed to the schema view (added in a later task) so schema generation
# only ever traverses these routes.
api_urlpatterns = [
    path("", views.StacLandingPageView.as_view(), name="landing-page"),
    path("conformance/", views.StacConformanceView.as_view(), name="conformance"),
]

urlpatterns = api_urlpatterns
