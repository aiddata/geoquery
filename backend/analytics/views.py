from datetime import timedelta

from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.tasks.ingest import ingest_custom_boundary_task
from analytics.tasks.email import GeoEmail
from analytics.throttles import RequestSubmitThrottle, RequestTokenThrottle
from .models import Request, RequestToken
from .services import (
    STATUS_LABELS as _STATUS_LABELS,
    NoExtractTasksError,
    create_request,
    request_links,
    requests_for_user,
)


class RequestView(APIView):
    """
    GET  /api/analytics/requests/?email=  — list requests submitted by an email address
    POST /api/analytics/requests/         — submit a new extraction request
    """

    # DRF enforces CSRF only for session-authenticated requests, so anonymous
    # submissions still work without a token while logged-in submissions must
    # send X-CSRFToken (the frontend fetch wrapper handles this).
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [RequestSubmitThrottle]

    def get(self, request):
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    @transaction.atomic
    def post(self, request):
        name = (request.data.get("name") or "").strip()
        email = (request.data.get("email") or "").strip()
        user = request.user if request.user.is_authenticated else None
        feature_ids = request.data.get("featureIds") or []
        datasets = request.data.get("datasets") or []
        custom_boundary = request.data.get("customBoundary")

        if not email:
            return Response(
                {"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "a valid email address is required"},
                status=status.HTTP_400_BAD_REQUEST,
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
                    {
                        "error": "customBoundary.features must be a GeoJSON FeatureCollection"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            features_list = geojson_fc.get("features") or []
            if not features_list:
                return Response(
                    {"error": "customBoundary.features has no features"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            max_features = getattr(settings, "CUSTOM_BOUNDARY_MAX_FEATURES", 100_000)
            if len(features_list) > max_features:
                return Response(
                    {
                        "error": f"Custom boundary may not exceed {max_features:,} features."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            selection_label = (request.data.get("selectionLabel") or "").strip() or None
            selection_detail = (request.data.get("selectionDetail") or "").strip() or None
            upload_metadata = {
                "fileName": custom_boundary.get("fileName"),
                "featureCount": custom_boundary.get("featureCount"),
                "operations": custom_boundary.get("operations") or [],
            }

            req = Request.objects.create(
                contact=email,
                custom_name=name or None,
                user=user,
                source="web_custom",
                status=3,
                data={
                    "selection_label": selection_label,
                    "selection_detail": selection_detail,
                    "is_custom_boundary": True,
                    "boundary_file_name": upload_metadata.get("fileName"),
                    "boundary_operations": upload_metadata.get("operations") or [],
                    "boundary_feature_count": upload_metadata.get("featureCount"),
                    "upload_metadata": upload_metadata,
                },
            )

            ingest_custom_boundary_task.delay(
                str(req.id),
                geojson_fc,
                datasets,
                user.id if user else None,
            )

            return Response(
                {
                    "id": str(req.id),
                    "name": req.custom_name,
                    "status": req.status,
                    "status_label": _STATUS_LABELS.get(req.status, "unknown"),
                    "submit_time": req.submit_time,
                    "task_count": None,
                },
                status=status.HTTP_201_CREATED,
            )

        # ── Standard boundary submission path ─────────────────────────────────────
        if not feature_ids:
            return Response(
                {"error": "featureIds is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Everything from here -- visibility resolution, task reuse, warning
        # wording, the Request row itself -- lives in analytics.services so the
        # MCP server creates requests exactly the way the web app does.
        try:
            created = create_request(
                user=user,
                contact=email,
                name=name,
                feature_ids=feature_ids,
                datasets=datasets,
                selection_label=(request.data.get("selectionLabel") or "").strip()
                or None,
                selection_detail=(request.data.get("selectionDetail") or "").strip()
                or None,
                source="web",
            )
        except NoExtractTasksError as exc:
            return Response(
                {
                    "error": "No extract tasks found for the submitted datasets.",
                    "warnings": exc.warnings,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(created.as_response_dict(), status=status.HTTP_201_CREATED)


class RequestDetailView(APIView):
    """
    GET /api/analytics/requests/{id}/ — retrieve a single request by UUID
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, pk):
        from django.db.models import Count

        try:
            req = Request.objects.annotate(task_count=Count("requestmap")).get(id=pk)
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
                        boundary_file_name = (
                            boundary_file_name or fc.upload_metadata.get("fileName")
                        )
                        boundary_feature_count = (
                            boundary_feature_count
                            or fc.upload_metadata.get("featureCount")
                        )
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
            "task_count": req.task_count,
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

        data.update(request_links(req))

        return Response(data)


class RequestTokenView(APIView):
    """
    POST /api/analytics/request-token/ — issue or refresh a magic-link token for an email
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RequestTokenThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response(
                {"error": "email is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "a valid email address is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expiry_months = getattr(settings, "TOKEN_EXPIRY_MONTHS", 6)
        expires_at = timezone.now() + timedelta(days=30 * expiry_months)

        _, raw_token = RequestToken.create_for_email(email=email, expires_at=expires_at)

        base_url = getattr(
            settings, "FRONTEND_BASE_URL", "http://localhost:5173"
        ).rstrip("/")
        magic_link = f"{base_url}/requests/{raw_token}"

        subject = "Your GeoQuery request history link"
        message = (
            f"Here is your personal link to view your GeoQuery request history:\n\n"
            f"{magic_link}\n\n"
            f"This link will expire on {expires_at.strftime('%B %d, %Y')}.\n\n"
            f"If you did not request this link, you can safely ignore this email."
        )
        send_status, _, exc = GeoEmail().send_email(email, subject, message)
        if not send_status:
            return Response(
                {"error": "Failed to send email. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"detail": "Link sent. Check your email."}, status=status.HTTP_200_OK
        )


class RequestHistoryView(APIView):
    """
    GET /api/analytics/history/<token>/ — return request history for a valid token
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            token_obj = RequestToken.objects.get(token=RequestToken.hash_token(token))
        except RequestToken.DoesNotExist:
            return Response(
                {"error": "Invalid or expired link."}, status=status.HTTP_404_NOT_FOUND
            )

        if token_obj.is_expired:
            return Response(
                {"error": "This link has expired. Please request a new one."},
                status=status.HTTP_410_GONE,
            )

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


class MyRequestsView(APIView):
    """
    GET /api/analytics/my-requests/ — request history for the logged-in user
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = requests_for_user(request.user)
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
