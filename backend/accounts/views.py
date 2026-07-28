from django.http import HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def csrf_view(request):
    """Set the ``csrftoken`` cookie so the SPA can read it and send X-CSRFToken.

    Session-authenticated unsafe requests (a logged-in user submitting a
    request, allauth headless POSTs) require the CSRF token. The SPA calls this
    once to bootstrap the cookie when it isn't already present.
    """
    return HttpResponse(status=204)
