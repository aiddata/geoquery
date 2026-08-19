from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

app_name = "public_api"

# Populated by later tasks as real endpoints are added. Passed to the
# schema view below so OpenAPI generation only ever traverses these
# routes, never the internal /api/* endpoints used by the frontend.
api_urlpatterns = []

urlpatterns = api_urlpatterns + [
    path(
        "schema/",
        SpectacularAPIView.as_view(patterns=api_urlpatterns),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="public_api:schema"),
        name="docs",
    ),
]
