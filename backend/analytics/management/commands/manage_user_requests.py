"""
Manage processing of user requests
Includes: updating status, handling errors, queue management and task submissions, doc/request building, emails, etc.)
"""
import os
import json
import shutil
import textwrap
import time
import zipfile
from logging import getLogger
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.tasks.email import GeoEmail
from analytics.tasks.documentation import DocBuilder
from analytics.tasks.merge import merge_task_results, merge_task_features
from visualize.builder import VizBuilder

logger = getLogger(__name__)


class Command(BaseCommand):
    help = "Handles the generation of extract tasks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Whether to run the command without making any changes to the database (for testing)",
        )
        parser.add_argument(
            "--id",
            default=False,
            help="The ID of a specific request to process",
        )
        parser.add_argument(
            "--download-server",
            default="geoquery.aiddata.wm.edu",
            help="The server that users will download data from (used in email notifications)",
        )
        parser.add_argument(
            "--results-dir",
            default="../results",
            help="The directory containing results for the request",
        )
        parser.add_argument(
            "--assets-dir",
            default="../assets",
            help="The directory containing assets for the request (e.g. documentation templates, example docs, etc.)",
        )

    def handle(self, *args, **options):
        _manage_user_requests(
            request_id=options["id"] or None,
            download_server=options["download_server"],
            results_dir=options["results_dir"],
            assets_dir=options["assets_dir"],
            dry_run=options["dry_run"],
        )


def _manage_user_requests(
    request_id=None,
    download_server="geoquery.aiddata.wm.edu",
    results_dir="../results",
    assets_dir="../assets",
    dry_run=False,
):
    logger.info("Starting User Request Management Script %s", time.strftime("%Y-%m-%d %H:%M:%S"))

    if request_id:
        logger.info("Processing request with id: %s", request_id)
    else:
        logger.info("Processing all requests in queue")

    request_objects = []

    if request_id:
        request = Request.objects.get(id=request_id)
        if not request:
            logger.error("Error finding request with id (%s)", request_id)
            return
        request_objects.append(request)
    else:
        request_objects += list(Request.objects.filter(status=-1).order_by("-priority", "submit_time"))
        request_objects += list(Request.objects.filter(status=0).order_by("-priority", "submit_time"))

    if not request_objects:
        logger.warning("Request queue is empty")
        return

    for request_obj in request_objects:
        request_id = str(request_obj.id)
        logger.info("Request (id: %s)\n%s", request_id, request_obj)

        try:
            with transaction.atomic():
                if not request_obj.data:
                    _request_error(request_id, "Invalid request (missing items field)")
                    continue
                if not request_obj.data["feature_ids"]:
                    _request_error(request_id, "Invalid request (missing features)")
                    continue
                if not request_obj.data["datasets"]:
                    _request_error(request_id, "Invalid request (missing dataset details)")
                    continue

                logger.info("Features: %s (%s)", request_obj.data["selection_label"], request_obj.data["selection_label"])

                original_status = Request.objects.get(id=request_id).status

                if original_status == -1:
                    Request.objects.filter(id=request_id).update(prepare_time=timezone.now())
                    _notify_user(request_id, request_obj.contact, 0, download_server)

                Request.objects.filter(id=request_id).update(status=2, process_time=timezone.now())

                missing_items, merge_list = _check_request_tasks(request_obj, dry_run=dry_run)

                if missing_items > 0:
                    Request.objects.filter(id=request_id).update(status=0)
                    logger.warning("Request not ready (id: %s)", request_id)
                else:
                    updated_request_obj = Request.objects.get(id=request_id)
                    _build_output(updated_request_obj, merge_list, download_server, results_dir, assets_dir)
                    Request.objects.filter(id=request_id).update(status=1, complete_time=timezone.now())
                    _notify_user(request_id, updated_request_obj.contact, 1, download_server)
                    logger.info("Request completed (id: %s)", request_id)

                if dry_run:
                    Request.objects.filter(id=request_id).update(status=original_status)

        except Exception as e:
            _request_error(request_id, f"Unhandled exception: {e}")
            logger.error("Skipping request (id: %s) due to error", request_id)

    logger.info("Finished User Request Management Script %s", time.strftime("%Y-%m-%d %H:%M:%S"))


def _request_error(request_id, message):
    logger.error("Error with request (id: %s): %s", request_id, message)
    Request.objects.filter(id=request_id).update(status=-2)


def _notify_user(request_id, mail_to, status, download_server):
    """Send email that request was received (status=0) or completed (status=1)."""
    if status not in [0, 1]:
        raise ValueError(f"Invalid status for _notify_user: {status}. Status must be 0 or 1.")

    status_text = "Received" if status == 0 else "Completed"
    mail_subject = f"AidData GeoQuery- Request {request_id[:7]}.. {status_text}"

    received_message = textwrap.dedent(f"""
        Thanks for using GeoQuery. This is an automated email to let you
        know that we received your request and will process your data as
        soon as we can. We will send another email when your data is ready.

        You can view the status of this data request here:
        http://{download_server}/query/#!/status/{request_id}

        You can also keep track of all of the data requests that you've
        submitted with this email address here:
        http://{download_server}/query/#!/requests/{mail_to}

        Thank you,
        \tAidData's GeoQuery Team
    """)

    completed_message = textwrap.dedent(f"""
        Thanks again for using GeoQuery. This is another automated email to let you know that
        your data is ready.

        You can review your request, and download the results and documentation here:
        \thttp://{download_server}/query/#!/status/{request_id}

        Or download the results directly (this link will always be available):
        \thttp://{download_server}/data/geoquery_results/{request_id}/{request_id}.zip

        You can also view all your current and previous requests using:
        \thttp://{download_server}/query/#!/requests/{mail_to}

        Also, one quick reminder about citations. Don't forget to cite both AidData's GeoQuery
        tool as well as each dataset you selected within GeoQuery. All citations can be found
        in the Documentation PDF at the link above. Here's the correct citation for GeoQuery:

            Goodman, S., BenYishay, A., Lv, Z., & Runfola, D. (2019).
            GeoQuery: Integrating HPC systems and public web-based
            geospatial data tools. Computers & Geosciences, 122, 103-112.

        Thank you in advance for citing us when you publish your research.
        This helps us to demonstrate how GeoQuery is making a difference
        as a freely available public good.

        Thank you,
        \tAidData's GeoQuery Team
    """)

    mail_message = received_message if status == 0 else completed_message

    mail_status = GeoEmail().send_email(mail_to, mail_subject, mail_message)
    if not mail_status[0]:
        logger.error("%s: %s", mail_status[1], mail_status[2])
        Request.objects.filter(id=request_id).update(status=-2)


def _check_request_tasks(request, dry_run=False):
    """Check entire request for completion.

    Returns count of tasks still pending and list of completed extract task IDs.
    """
    pending_task_count = 0
    completed_task_list = []

    logger.info("Checking status of processing tasks (dry_run=%s)...", dry_run)

    task_list = RequestMap.objects.filter(request=request.id)

    for task_item in task_list:
        extract_task = ExtractTask.objects.filter(id=task_item.task_id).first()
        if extract_task.status != 1:
            pending_task_count += 1
            # increase priority of pending tasks to ensure they get processed before non request tasks
            extract_task.priority = 1
        else:
            completed_task_list.append(extract_task.id)

    logger.info("Processing tasks pending: %d/%d", pending_task_count, len(task_list))

    return pending_task_count, completed_task_list


def _build_output(request, task_list, download_server, results_dir, assets_dir):
    """Merge extracts, generate documentation, build zip."""
    results_dir = Path(results_dir)
    assets_dir = Path(assets_dir)

    request_id = str(request.id)
    request_dir = results_dir / request_id

    shutil.rmtree(request_dir, ignore_errors=True)
    request_dir.mkdir(parents=True, exist_ok=True)

    request_csv = request_dir / f"{request_id}_results.csv"
    request_documentation = request_dir / f"{request_id}_documentation.html"
    request_json = request_dir / "request_details.json"

    merge_status, merge_df = merge_task_results(task_list)
    if merge_status != "Success":
        raise Exception(f"No extracts merged for request {request_id}. Merge status: {merge_status}")
    logger.info("Merge completed for request %s", request_id)
    merge_df.to_csv(request_csv, index=False)

    doc = DocBuilder(request, request_documentation, download_server)
    bd_status = doc.build_doc()
    if bd_status != "Success":
        raise Exception(f"Error building documentation for request {request_id}. Status: {bd_status}")
    logger.info("Documentation generated for request %s", request_id)

    request_visualization = request_dir / f"{request_id}_visualization.html"
    viz = VizBuilder(request, merge_df, request_visualization)
    viz_status = viz.build_viz()
    if viz_status != "Success":
        logger.warning("Visualization skipped: %s", viz_status)
    else:
        logger.info("Visualization generated for request %s", request_id)

    with open(request_json, "w") as rdoc_file:
        json.dump(
            {k: v for k, v in request.__dict__.items() if not k.startswith("_")},
            rdoc_file,
            indent=4,
            default=str,
        )

    pdf_src = assets_dir / "other/GeoQuery_Goodman2019.pdf"
    pdf_dst = request_dir / "GeoQuery_Goodman2019.pdf"
    shutil.copyfile(pdf_src, pdf_dst)

    features_status, features_gdf = merge_task_features(task_list)
    if features_status == "Success":
        features_gdf.to_file(request_dir / "request_features.gpkg", driver="GPKG")
    elif features_status == "Empty":
        logger.info("No features to merge for request %s", request_id)
    else:
        raise Exception(f"Error merging features for request {request_id}. Status: {features_status}")

    make_zipfile(request_dir, request_dir)
    shutil.move(str(request_dir) + ".zip", str(request_dir))
    os.remove(pdf_dst)

    os.chmod(request_dir, 0o775)
    for ro, di, fi in os.walk(request_dir):
        for d in di:
            os.chmod(os.path.join(ro, d), 0o775)
        for f in fi:
            os.chmod(os.path.join(ro, f), 0o664)


def make_zipfile(base_name, base_dir):
    """Create a zip file from all the files under 'base_dir'.

    The output zip file will be named 'base_name' + ".zip".

    *** Modified from shutil.make_archive
    """
    zip_filename = Path(str(base_name) + ".zip")
    archive_dir = zip_filename.parent
    archive_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        length = len(str(base_dir))
        for dirpath, dirnames, filenames in os.walk(base_dir):
            folder = dirpath[length:]
            for name in filenames:
                actual_path = os.path.normpath(os.path.join(dirpath, name))
                zip_path = os.path.normpath(os.path.join(folder, name))
                if os.path.isfile(actual_path):
                    zf.write(actual_path, zip_path)
    return zip_filename
