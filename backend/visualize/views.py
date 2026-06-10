from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Request

from .data import build_request_data


class RequestVisualizationDataView(APIView):
    """
    GET /api/visualize/request/<uuid:id>/

    Returns the data payload for rendering a request visualization in the
    frontend /viz/<id> route. Reads from the DB (extract_data + join chain),
    so improvements to the renderer apply retroactively to all past requests.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, id):
        try:
            req = Request.objects.get(id=id)
        except Request.DoesNotExist:
            return Response({"error": "Request not found"}, status=404)

        return Response(build_request_data(req))