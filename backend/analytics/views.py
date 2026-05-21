import json

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from features.models import FeatureCollection

from .models import ExtractTask, Request, RequestMap

_STATUS_LABELS = {
    -2: "error",
    -1: "queued",
    0: "processing",
    1: "completed",
    2: "preparing",
}


class RequestView(APIView):
    """
    GET  /api/analytics/requests/?email=  — list requests submitted by an email address
    POST /api/analytics/requests/         — submit a new extraction request
    """

    authentication_classes = []  # no session auth → no CSRF re-enforcement
    permission_classes = [AllowAny]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return Response(
                {"error": "email parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = Request.objects.filter(contact=email).order_by("-submit_time")
        data = [
            {
                "id": str(r.id),
                "name": r.custom_name,
                "status": r.status,
                "status_label": _STATUS_LABELS.get(r.status, "unknown"),
                "submit_time": r.submit_time,
            }
            for r in qs
        ]
        return Response(data)

    @transaction.atomic
    def post(self, request):
        name = (request.data.get("name") or "").strip()
        email = (request.data.get("email") or "").strip()
        items = request.data.get("items") or []

        if not email:
            return Response(
                {"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not items:
            return Response(
                {"error": "at least one item is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        all_task_ids: set[int] = set()
        warnings: list[str] = []

        for item in items:
            boundary_name = (item.get("boundaryName") or "").strip()
            dataset_name = (item.get("datasetName") or "").strip()
            extract_types = item.get("extractTypes") or []
            resources = item.get("resources") or []

            if not boundary_name or not dataset_name:
                warnings.append(
                    f"Skipped item missing boundaryName or datasetName: {item}"
                )
                continue

            if not FeatureCollection.objects.filter(
                name=boundary_name, active=True, public=True
            ).exists():
                warnings.append(f"Boundary not found: {boundary_name}")
                continue

            tasks = ExtractTask.objects.filter(
                fm__fc__name=boundary_name,
                resource__dataset__name=dataset_name,
            )
            if extract_types:
                tasks = tasks.filter(po__short_name__in=extract_types)
            if resources:
                tasks = tasks.filter(resource__name__in=resources)

            task_ids = list(tasks.values_list("id", flat=True))
            if not task_ids:
                warnings.append(
                    f"No extract tasks found for dataset '{dataset_name}' "
                    f"in boundary '{boundary_name}'"
                )
                continue

            all_task_ids.update(task_ids)

        if not all_task_ids:
            return Response(
                {"error": "No extract tasks found for the submitted items.", "warnings": warnings},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req = Request.objects.create(
            contact=email,
            custom_name=name or None,
            source="web",
            status=-1,
            info=json.dumps(items),
        )

        RequestMap.objects.bulk_create([
            RequestMap(request=req, task_id=task_id)
            for task_id in all_task_ids
        ])

        response_data = {
            "id": str(req.id),
            "name": req.custom_name,
            "status": req.status,
            "status_label": _STATUS_LABELS.get(req.status, "unknown"),
            "submit_time": req.submit_time,
            "task_count": len(all_task_ids),
        }
        if warnings:
            response_data["warnings"] = warnings

        return Response(response_data, status=status.HTTP_201_CREATED)
