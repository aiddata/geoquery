from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import Request

from .data import build_explore_available, build_explore_data, build_request_data
from .export import GistExporter


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


class ExploreAvailableView(APIView):
    """
    GET /api/visualize/explore/available/?fc=1,2,3

    Returns datasets + processing options that have completed extracts for
    the given FC IDs. Used to populate the option picker in /viz/explore.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        fc_param = request.query_params.get("fc", "").strip()
        if not fc_param:
            return Response({"error": "fc parameter is required"}, status=400)
        try:
            fc_ids = [int(v) for v in fc_param.split(",") if v.strip()]
        except ValueError:
            return Response({"error": "fc must be a comma-separated list of integers"}, status=400)

        return Response(build_explore_available(fc_ids))


class ExploreDataView(APIView):
    """
    GET /api/visualize/explore/?fc=1,2&po=3,4

    Returns the visualization payload for an ad-hoc selection of feature
    collections and processing options. Same shape as the request viz payload
    minus request-specific fields (request_id, request_status, etc.).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        fc_param = request.query_params.get("fc", "").strip()
        po_param = request.query_params.get("po", "").strip()
        if not fc_param or not po_param:
            return Response({"error": "fc and po parameters are required"}, status=400)
        try:
            fc_ids = [int(v) for v in fc_param.split(",") if v.strip()]
            po_ids = [int(v) for v in po_param.split(",") if v.strip()]
        except ValueError:
            return Response({"error": "fc and po must be comma-separated integers"}, status=400)

        return Response(build_explore_data(fc_ids, po_ids))


def request_export(request, id):
    fmt = request.GET.get("format", "").strip()
    if fmt not in ("colab", "marimo"):
        return JsonResponse({"error": "format must be 'colab' or 'marimo'"}, status=400)

    try:
        req = Request.objects.get(id=id)
    except Request.DoesNotExist:
        return JsonResponse({"error": "Request not found"}, status=404)

    if req.status != 1:
        return JsonResponse({"error": "Request is not completed"}, status=400)

    base = getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/")
    if not base:
        return JsonResponse({"error": "DOWNLOAD_BASE_URL is not configured"}, status=503)

    download_url = f"{base}/data/geoquery_results/{req.id}/{req.id}.zip"

    try:
        exporter = GistExporter(
            request_id=str(req.id),
            request_name=req.custom_name or "",
            download_url=download_url,
        )
        redirect_url = exporter.export(fmt)
    except (RuntimeError, ValueError) as e:
        return JsonResponse({"error": str(e)}, status=503)

    return HttpResponseRedirect(redirect_url)
