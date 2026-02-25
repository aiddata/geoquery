from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class ConfigView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "protomaps_api_key": settings.PROTOMAPS_API_KEY,
            }
        )
