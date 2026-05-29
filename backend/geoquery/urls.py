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

from geoquery.views import ConfigView
from stats.views import stats_view, workers_view

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    path("stats/workers/", workers_view, name="stats-workers"),
    path("admin/", admin.site.urls),
    path("api/config/", ConfigView.as_view(), name="config"),
    path("api/features/", include("features.urls")),
    path("api/datasets/", include("datasets.urls")),
    path("api/analytics/", include("analytics.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^data/geoquery_results/(?P<path>.*)$",
            serve,
            {"document_root": settings.RESULTS_DIR},
        ),
    ]
