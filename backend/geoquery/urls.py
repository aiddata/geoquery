"""
URL configuration for geoquery project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from stats.views import stats_view, workers_view

from geoquery.views import ConfigView
from stac_api.views import StacLandingPageView

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    path("stats/workers/", workers_view, name="stats-workers"),
    path("admin/", admin.site.urls),
    # Headless JSON auth API for the SPA: /api/_allauth/browser/v1/...
    path("api/_allauth/", include("allauth.headless.urls")),
    # Regular allauth URLs are still needed for the OAuth provider
    # redirect/callback round-trip; HEADLESS_ONLY prunes the HTML views.
    path("api/accounts/", include("allauth.urls")),
    path("api/auth/", include("accounts.urls")),
    path("api/config/", ConfigView.as_view(), name="config"),
    path("api/features/", include("features.urls")),
    path("api/datasets/", include("datasets.urls")),
    path("api/analytics/", include("analytics.urls")),
    path("api/visualize/", include("visualize.urls")),
    path("api/public/v1/", include("public_api.urls")),
    path("api/stac/v1/", include("stac_api.urls")),
    # Serves the catalog root directly at the no-trailing-slash path too.
    # Without this, Django's APPEND_SLASH redirects "/api/stac/v1" to
    # "/api/stac/v1/" via CommonMiddleware, before the view ever runs — so
    # the redirect response carries no CORS headers, and a browser treats
    # a redirected preflight as a failed one. This is the URL most STAC
    # clients get configured with by hand (the "catalog URL"), so it's the
    # one entry point worth avoiding the redirect for; everything reached
    # from the landing page's own links is already correctly slashed.
    path("api/stac/v1", StacLandingPageView.as_view()),
]

urlpatterns += [
    re_path(
        r"^requests/(?P<path>.*)$",
        serve,
        {"document_root": settings.REQUESTS_DIR},
    ),
]
