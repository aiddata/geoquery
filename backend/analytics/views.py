from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

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
        feature_ids = request.data.get("featureIds") or []
        datasets = request.data.get("datasets") or []

        if not email:
            return Response(
                {"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not feature_ids:
            return Response(
                {"error": "featureIds is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not datasets:
            return Response(
                {"error": "at least one dataset is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        all_task_ids: set[int] = set()
        warnings: list[str] = []
        valid_datasets: list[dict] = []

        for ds in datasets:
            dataset_name = (ds.get("datasetName") or "").strip()
            extract_types = ds.get("extractTypes") or []
            resources = ds.get("resources") or []

            if not dataset_name:
                warnings.append(f"Skipped dataset missing datasetName: {ds}")
                continue

            tasks = ExtractTask.objects.filter(
                fm__geom_id__in=feature_ids,
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
                    f"across {len(feature_ids)} feature(s)"
                )
                continue

            all_task_ids.update(task_ids)
            valid_datasets.append({
                "dataset_name": dataset_name,
                "dataset_type": (ds.get("datasetType") or "").strip() or None,
                "extract_types": extract_types,
                "resources": resources,
                "resource_labels": ds.get("resourceLabels") or [],
            })

        if not all_task_ids:
            return Response(
                {"error": "No extract tasks found for the submitted datasets.", "warnings": warnings},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req = Request.objects.create(
            contact=email,
            custom_name=name or None,
            source="web",
            status=-1,
            data={
                "selection_label": (request.data.get("selectionLabel") or "").strip() or None,
                "selection_detail": (request.data.get("selectionDetail") or "").strip() or None,
                "feature_ids": feature_ids,
                "datasets": valid_datasets,
            },
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


class RequestDetailView(APIView):
    """
    GET /api/analytics/requests/{id}/ — retrieve a single request by UUID
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            req = Request.objects.get(id=pk)
        except Request.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        req_data = req.data or {}

        data = {
            "id": str(req.id),
            "name": req.custom_name,
            "status": req.status,
            "status_label": _STATUS_LABELS.get(req.status, "unknown"),
            "submit_time": req.submit_time,
            "complete_time": req.complete_time,
            "task_count": RequestMap.objects.filter(request=req).count(),
            "data": {
                "selection_label": req_data.get("selection_label"),
                "selection_detail": req_data.get("selection_detail"),
                "feature_ids": req_data.get("feature_ids", []),
                "datasets": req_data.get("datasets", []),
            },
        }

        if req.status == 1:
            base = getattr(settings, "DOWNLOAD_BASE_URL", "").rstrip("/")
            if base:
                data["download_url"] = (
                    f"{base}/data/geoquery_results/{req.id}/{req.id}.zip"
                )
                data["documentation_url"] = (
                    f"{base}/data/geoquery_results/{req.id}/{req.id}_documentation.html"
                )
                data["visualization_url"] = (
                    f"{base}/data/geoquery_results/{req.id}/{req.id}_visualization.html"
                )

        return Response(data)
