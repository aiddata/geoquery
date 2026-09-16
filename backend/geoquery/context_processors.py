"""Template context shared by the few pages Django renders itself."""

from django.conf import settings


def frontend(request):
    """Expose the SPA's public base URL so server-rendered pages (allauth's
    OIDC consent screen, mainly) can link back to the site."""
    return {"frontend_base_url": settings.FRONTEND_BASE_URL.rstrip("/")}
