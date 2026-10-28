from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.features import BETA_FEATURES


class ConfigView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "protomaps_api_key": settings.PROTOMAPS_API_KEY,
                # Features limited to beta testers; the session user's
                # is_beta_tester flag says whether the caller is one.
                "beta_features": sorted(BETA_FEATURES),
            }
        )
