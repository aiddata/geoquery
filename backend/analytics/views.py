from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.ingest import ingest_custom_boundary
from analytics.tasks.email import GeoEmail
from .models import ExtractTask, Request, RequestMap, RequestToken

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
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    @transaction.atomic
    def post(self, request):
        name = (request.data.get("name") or "").strip()
        email = (request.data.get("email") or "").strip()
        feature_ids = request.data.get("featureIds") or []
        datasets = request.data.get("datasets") or []
        custom_boundary = request.data.get("customBoundary")

        if not email:
            return Response(
                {"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not isinstance(feature_ids, list) or not all(
            isinstance(i, int) for i in feature_ids
        ):
            return Response(
                {"error": "featureIds must be a list of integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not datasets:
            return Response(
                {"error": "at least one dataset is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Custom boundary submission path ───────────────────────────────────────
        if custom_boundary:
            geojson_fc = custom_boundary.get("features")
            if not geojson_fc or geojson_fc.get("type") != "FeatureCollection":
                return Response(
                    {"error": "customBoundary.features must be a GeoJSON FeatureCollection"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not geojson_fc.get("features"):
                return Response(
                    {"error": "customBoundary.features has no features"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                req, task_count, warnings = ingest_custom_boundary(
                    geojson_fc=geojson_fc,
                    datasets=datasets,
                    contact=email,
                    name=name or None,
                    selection_label=(request.data.get("selectionLabel") or "").strip() or None,
                    selection_detail=(request.data.get("selectionDetail") or "").strip() or None,
                    upload_metadata={
                        "fileName": custom_boundary.get("fileName"),
                        "featureCount": custom_boundary.get("featureCount"),
                        "operations": custom_boundary.get("operations") or [],
                    },
                )
            except ValueError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response(
                    {"error": f"Failed to ingest custom boundary: {e}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            response_data = {
                "id": str(req.id),
                "name": req.custom_name,
                "status": req.status,
                "status_label": _STATUS_LABELS.get(req.status, "unknown"),
                "submit_time": req.submit_time,
                "task_count": task_count,
            }
            if warnings:
                response_data["warnings"] = warnings
            return Response(response_data, status=status.HTTP_201_CREATED)

        # ── Standard boundary submission path ─────────────────────────────────────
        if not feature_ids:
            return Response(
                {"error": "featureIds is required"}, status=status.HTTP_400_BAD_REQUEST
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

        is_custom = req_data.get("is_custom_boundary", False)

        # Resolve boundary metadata: prefer request.data fields (new requests),
        # fall back to fc.upload_metadata for requests submitted before ingest stored them.
        boundary_operations = req_data.get("boundary_operations")
        boundary_file_name = req_data.get("boundary_file_name")
        boundary_feature_count = req_data.get("boundary_feature_count")
        if is_custom and boundary_operations is None:
            fc_id = req_data.get("fc_id")
            if fc_id:
                try:
                    from features.models import FeatureCollection
                    fc = FeatureCollection.objects.filter(id=fc_id).first()
                    if fc and fc.upload_metadata:
                        boundary_operations = fc.upload_metadata.get("operations") or []
                        boundary_file_name = boundary_file_name or fc.upload_metadata.get("fileName")
                        boundary_feature_count = boundary_feature_count or fc.upload_metadata.get("featureCount")
                except Exception:
                    pass
        if boundary_operations is None:
            boundary_operations = []

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
                "is_custom_boundary": is_custom,
                "boundary_file_name": boundary_file_name,
                "boundary_feature_count": boundary_feature_count,
                "boundary_operations": boundary_operations,
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
            frontend_base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
            if frontend_base:
                data["visualization_url"] = f"{frontend_base}/viz/{req.id}"

        return Response(data)


class RequestTokenView(APIView):
    """
    POST /api/analytics/request-token/ — issue or refresh a magic-link token for an email
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST)

        expiry_months = getattr(settings, "TOKEN_EXPIRY_MONTHS", 6)
        expires_at = timezone.now() + timedelta(days=30 * expiry_months)

        token_obj, _ = RequestToken.objects.update_or_create(
            email=email,
            defaults={"expires_at": expires_at},
        )
        # update_or_create won't call save() for new tokens so generate token manually
        if not token_obj.token:
            import secrets
            token_obj.token = secrets.token_urlsafe(32)
            token_obj.save(update_fields=["token"])

        base_url = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
        magic_link = f"{base_url}/requests/{token_obj.token}"

        subject = "Your GeoQuery request history link"
        message = (
            f"Here is your personal link to view your GeoQuery request history:\n\n"
            f"{magic_link}\n\n"
            f"This link will expire on {expires_at.strftime('%B %d, %Y')}.\n\n"
            f"If you did not request this link, you can safely ignore this email."
        )
        send_status, _, exc = GeoEmail().send_email(email, subject, message)
        if not send_status:
            return Response({"error": "Failed to send email. Please try again later."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"detail": "Link sent. Check your email."}, status=status.HTTP_200_OK)


class RequestHistoryView(APIView):
    """
    GET /api/analytics/history/<token>/ — return request history for a valid token
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            token_obj = RequestToken.objects.get(token=token)
        except RequestToken.DoesNotExist:
            return Response({"error": "Invalid or expired link."}, status=status.HTTP_404_NOT_FOUND)

        if token_obj.is_expired:
            return Response({"error": "This link has expired. Please request a new one."}, status=status.HTTP_410_GONE)

        qs = Request.objects.filter(contact=token_obj.email).order_by("-submit_time")
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
