from django.http import HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User


@ensure_csrf_cookie
def csrf_view(request):
    """Set the ``csrftoken`` cookie so the SPA can read it and send X-CSRFToken.

    Session-authenticated unsafe requests (a logged-in user submitting a
    request, allauth headless POSTs) require the CSRF token. The SPA calls this
    once to bootstrap the cookie when it isn't already present.
    """
    return HttpResponse(status=204)


class PreferencesView(APIView):
    """PATCH /api/auth/preferences/ {"theme": "system" | "light" | "dark"}

    Saves the signed-in user's site preferences, so they follow the user
    between devices. The SPA reads them back from allauth's session payload
    (``accounts.adapter.HeadlessAdapter``), so there's no GET.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        theme = request.data.get("theme")
        if theme not in User.Theme.values:
            return Response(
                {"error": f"theme must be one of: {', '.join(User.Theme.values)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.theme = theme
        request.user.save(update_fields=["theme"])
        return Response({"theme": theme})
