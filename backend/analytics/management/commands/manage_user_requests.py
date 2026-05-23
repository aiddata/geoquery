"""
TODO: Placeholder for processing of user requests
Includes: updating status, handling errors, queue management and task submissions, doc/request building, emails, etc.)
"""
import sys
import os
import json
import shutil
import textwrap
import time
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from datasets.models import Dataset, DatasetResource
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ProcessingOption, Request, RequestMap
from analytics.tasks.email import GeoEmail
from analytics.tasks.documentation import DocBuilder
from analytics.tasks.merge import merge_task_results, merge_task_features

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
            "--assets-dir",
            default="./assets",
            help="The directory containing assets for the request documentation",
        )

    @transaction.atomic
    def handle(self, *args, **options):

        self.stdout.write(
            self.style.SUCCESS(
                f"""
                =======================================
                Starting User Request Management Script
                {time.strftime('%Y-%m-%d  %H:%M:%S', time.localtime())}
                """
            )
        )


        if options["id"]:
            request_id = options["id"]
            self.stdout.write(f"Processing request with id: {request_id}")
        else:
            self.stdout.write("Processing all requests in queue")
            request_id = None

        request_objects = []


        # from geoquery_requests import QueueToolBox
        # queue = QueueToolBox()

        # run if given a request_id via input arg
        if request_id:
            request = Request.objects.get(id=request_id)

            # check for request with given id
            # return request data object if request exists else None
            if not request:
                self.stdout.write(self.style.ERROR(f"Error finding request with id ({request_id})"))
                return

            request_objects += [request]

        else:
            # get list of requests in queue based on status, priority and submit time
            #
            # check for new unprocessed requests (status -1) first, before
            # checking status of requests with items already in queue (status 0)
            #   - new requests may have items that need to be added to queue, or might already be done

            request_objects += Request.objects.filter(status=-1).order_by("-priority", "submit_time")
            request_objects += Request.objects.filter(status=0).order_by("-priority", "submit_time")


        # verify that we have some requests
        if len(request_objects) == 0:
            self.stdout.write(self.style.WARNING("Request queue is empty"))
            return

        # go through found requests, checking status of items in processing queue,
        # building final output when ready and emailing user who requested data
        for request_obj in request_objects:

            request_id = str(request_obj.id)

            self.stdout.write(f"\n---------------------------------------")
            self.stdout.write(f"Request (id: {request_id})\n{request_obj}\n")

            if not request_obj.features or not request_obj.data:
                Request.objects.filter(id=request_id).update(status=-2)
                self.stdout.write(self.style.ERROR(f"Invalid request (missing key fields). Id: {request_id}"))
                continue


            self.stdout.write(f"Boundary: {request_obj.boundary.name}")

            original_status = Request.objects.get(id=request_id).status

            if original_status == -1:
                # update initial prepare_time
                Request.objects.filter(id=request_id).update(prepare_time=time.time())
                # send email that request was received
                self.notify_user(request_id, request_obj.contact, 0, options['download_server'])

            # set status 2 (no email)
            Request.objects.filter(id=request_id).update(status=2)

            # run core checks to see if request is ready to be built and emailed, and get list of missing items if not ready
            try:
                missing_items, merge_list = self.check_request_tasks(request_obj, dry_run=options['dry_run'])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error while running check_request_tasks (id: {request_id})"))
                Request.objects.filter(id=request_id).update(status=-2)
                raise


            if missing_items > 0:
                # set status 0 (do not send an email)
                Request.objects.filter(id=request_id).update(status=0)
                self.stdout.write(self.style.WARNING(f"Request not ready (id: {request_id})"))

            else:

                # pull request again, since check_request_tasks may have updated fields
                try:
                    updated_request_obj = Request.objects.get(id=request_id)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error while checking for updated request (id: {request_id})"))
                    raise

                if updated_request_obj is None:
                    self.stdout.write(self.style.ERROR(f"Error getting updated request: Request with id does not exist ({request_id})"))
                    raise Exception(f"Error getting updated request: Request with id does not exist ({request_id})")

                try:
                    # build request output/docs/zip/etc
                    self.build_output(updated_request_obj, merge_list, options['download_server'], options['assets_dir'])
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error while building request output (id: {request_id})"))
                    Request.objects.filter(id=request_id).update(status=-2)
                    raise e

                # set status 1 and send email that request is completed
                Request.objects.filter(id=request_id).update(status=1)
                self.notify_user(request_id, updated_request_obj.contact, 1, options['download_server'])

                self.stdout.write(self.style.SUCCESS(f"Request completed (id: {request_id})"))

            ###
            # for testing
            if options['dry_run']:
                Request.objects.filter(id=request_id).update(status=original_status)
            ###

            self.stdout.write(
                self.style.SUCCESS(
                    f"""
                    =======================================
                    Finished User Request Management Script
                    {time.strftime('%Y-%m-%d  %H:%M:%S', time.localtime())}
                    """
                )
            )


    def notify_user(self, request_id, mail_to, status, download_server):
        """send email that request was received or completed
        """
        GE = GeoEmail()

        if status not in [0, 1]:
            raise ValueError(f"Invalid status for notify_user: {status}. Status must be 0 or 1.")

        status_text = "Received" if status == 0 else "Completed"

        mail_subject = (f"AidData GeoQuery- Request {request_id[:7]}.. {status_text}")

        received_message = (
            f"""
            Thanks for using GeoQuery. This is an automated email to let you
            know that we received your request and will process your data as
            soon as we can. We will send another email when your data is ready.

            You can view the status of this data request here:
            http://{0}/query/#!/status/{1}

            You can also keep track of all of the data requests that you've
            submitted with this email address here:
            http://{0}/query/#!/requests/{2}

            Thank you,
            \tAidData's GeoQuery Team
            """).format(download_server, request_id, mail_to)

        completed_message = (
            """
            Thanks again for using GeoQuery. This is another automated email to let you know that
            your data is ready.

            You can review your request, and download the results and documentation here:
            \thttp://{0}/query/#!/status/{1}

            Or download the results directly (this link will always be available):
            \thttp://{0}/data/geoquery_results/{1}/{1}.zip

            You can also view all your current and previous requests using:
            \thttp://{0}/query/#!/requests/{2}

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
            """).format(download_server, request_id, mail_to)

        if status == 0:
            mail_message = received_message
        else:
            mail_message = completed_message

        mail_message = textwrap.dedent(mail_message)

        mail_status = GE.send_email(mail_to, mail_subject, mail_message)

        if not mail_status[0]:
            self.stdout.write(self.style.ERROR(mail_status[1]))
            update_status = Request.objects.filter(id=request_id).update(status=-2)
            # raise mail_status[2]


    def check_request_tasks(self, request, dry_run=False):
        """check entire request for completion

        return count of tasks still pending and list of processing tasks to merge
        """
        pending_task_count = 0
        completed_task_list = []

        self.stdout.write("\nChecking status of processing tasks (dry=run = {})...".format(dry_run))

        # TODO: combine the RequestMap and ExtractTask queries into one
        task_list = RequestMap.objects.filter(req_id=request['id'])

        for task_item in task_list:
            extract_task = ExtractTask.objects.filter(id=task_item.task_id)
            if extract_task.status != 1:
                pending_task_count += 1
            else:
                completed_task_list.append(extract_task.id)

        self.stdout.write('Processing tasks pending: {0}/{1}'.format(pending_task_count, len(task_list)))

        return pending_task_count, completed_task_list


    def build_output(self, request, task_list, download_server, results_dir,assets_dir):
        """build output

        merge extracts, generate documentation, update status,
            cleanup working directory, send final email
        """
        assets_dir = Path(assets_dir)
        results_dir = Path(results_dir) # "/path/to/request_data"

        request_id = str(request.id)
        request_dir = results_dir / request_id

        # clear any existing files in request dir
        shutil.rmtree(request_dir, ignore_errors=True)
        # create request dir
        request_dir.mkdir(parents=True, exist_ok=True)

        request_csv = request_dir / "{0}_results.csv".format(request_id)
        request_documentation = request_dir / "{0}_documentation.pdf".format(request_id)
        request_json = request_dir / "request_details.json"

        # merge cached results if all are available
        merge_status, merge_df = merge_task_results(task_list)

        if merge_status != "Success":
            raise Exception(f'\tWarning: no extracts merged for request {request_id}. Merge status: {merge_status}')
        else:
            self.stdout.write(f'\tMerge completed for request {request_id}')
            merge_df.to_csv(request_csv, index=False)

        # # TODO: generate documentation. Update to markdown/pandocs or something similar?
        # doc = DocBuilder(request, request_documentation, download_server)
        # bd_status = doc.build_doc()

        # if bd_status != "Success":
        #     raise Exception(f'\tError building documentation for request {request_id}. Status: {bd_status}')
        # else:
        #     self.stdout.write(f'\tDocumentation generated for request {request_id}')

        # output request doc as json
        with open(request_json, "w") as rdoc_file:
            json.dump(request, rdoc_file, indent=4)

        pdf_src = assets_dir / "other/GeoQuery_Goodman2019.pdf"
        pdf_dst = request_dir / "GeoQuery_Goodman2019.pdf"
        shutil.copyfile(pdf_src, pdf_dst)

        # dump all feature data into a GPKG in request dir
        features_gdf = merge_task_features(task_list)
        features_dst = request_dir / "request_features.gpkg"
        features_gdf.to_file(features_dst, driver="GPKG")

        # make zip of request dir
        # shutil.make_archive(request_dir, "zip", request_dir)
        make_zipfile(request_dir, request_dir)

        # move zip of request dir into request dir
        shutil.move(request_dir + ".zip", request_dir)

        # remove unzipped files which do not need direct access
        os.remove(pdf_dst)

        # set permissions
        os.chmod(request_dir, 0o775)
        for ro, di, fi in os.walk(request_dir):
            for d in di:
                os.chmod(os.path.join(ro, d), 0o775)
            for f in fi:
                os.chmod(os.path.join(ro, f), 0o664)

        return


def make_zipfile(base_name, base_dir):
    """Create a zip file from all the files under 'base_dir'.

    The output zip file will be named 'base_name' + ".zip".

    *** Modified from shutil.make_archive
    """
    zip_filename = Path(base_name + ".zip")
    archive_dir = zip_filename.parent
    archive_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_filename, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        length = len(base_dir)
        for dirpath, dirnames, filenames in os.walk(base_dir):
            folder = dirpath[length:]
            for name in filenames:
                actual_path = os.path.normpath(os.path.join(dirpath, name))
                zip_path = os.path.normpath(os.path.join(folder, name))
                if os.path.isfile(actual_path):
                    zf.write(actual_path, zip_path)
    return zip_filename
