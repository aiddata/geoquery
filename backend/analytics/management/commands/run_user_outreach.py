
import queue
import time
import textwrap
import time
import pandas as pd

from django.core.management.base import BaseCommand
from django.db import connection

from analytics.tasks.email import GeoEmail
from analytics.models import Request


class Command(BaseCommand):
    help = "Send email to admin about users who satisfy criteria for contact (e.g. multiple requests within timeframe but no contact or comments requested flags)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Do not actually dispatch tasks, just print how many would be dispatched",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of emails to send per batch (should really be per day for gmail limits, but we don'ty typically run this more than once per week so it should be fine)",
        )
        parser.add_argument(
            "--mode",
            type=str,
            default="manual",
            help="Whether to just flag users for manual contact by staff, or to automatically send emails to users. Options are 'manual' and 'auto'. Manual is the default and recommended mode.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="Number of days to look back when searching for users to contact. Default is 365.",
        )
        parser.add_argument(
            "--request-count",
            type=int,
            default=3,
            help="Minimum number of requests within the specified number of days to qualify for contact. Default is 3.",
        )
        parser.add_argument(
            "--earliest-request",
            type=int,
            default=14,
            help="Minimum number of days since earliest request to qualify for contact. Default is 14.",
        )
        parser.add_argument(
            "--latest-request",
            type=int,
            default=7,
            help="Minimum number of days since latest request to qualify for contact. Default is 7.",
        )


    def handle(self, *args, **options):
        """
        This command identifies users who satisfy criteria for contact (e.g. multiple requests within timeframe but no contact or comments requested flags) and either automatically sends them an email requesting comments or flags them for manual contact by staff.
        """

        current_timestamp = int(time.time())

        # filters for searching requests
        f = {
            "n_days": options["days"],
            "request_count": options["request_count"],
            "earliest_request": options["earliest_request"],
            "latest_request": options["latest_request"]
        }

        def to_seconds(days):
            """convert days to seconds"""
            return days*24*60*60

        # get timestamp for ndays before present time
        # used to get requests for past n days
        search_timestamp = current_timestamp - to_seconds(f["n_days"])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM requests
                WHERE submit_time > to_timestamp(%s)
                """,
                [search_timestamp],
            )
            request_objects = cursor.fetchall()

        if not request_objects:
            self.stdout.write(
                self.style.WARNING(
                    f"No requests found within past {f['n_days']} days. Exiting."
                )
            )
            return

        # convert to dataframe
        request_df_data = []

        for r in request_objects:
            request_dict = {
                'contact': r['contact'],
                'contact_flag': r['contact_flag'],
                'request_time': r['submit_time'],
                'complete_time': r['complete_time'],
                'status': r['status'],
                'count': 1
            }

            if 'comments_requested' in r:
                request_dict['comments_requested'] = r['comments_requested']
            else:
                request_dict['comments_requested'] = 0

            if 'contact_flag' in r:
                request_dict['contact_flag'] = r['contact_flag']
            else:
                request_dict['contact_flag'] = 0

            request_df_data.append(request_dict)


        request_df = pd.DataFrame(request_df_data)

        # time_field = "request_time"
        time_field = "complete_time"

        request_df["earliest_time"] = request_df[time_field]
        request_df["latest_time"] = request_df[time_field]


        # convert to user aggregated dataframe
        user_df = request_df.groupby('contact', as_index=False).agg({
            "count": "sum",
            "comments_requested": "sum",
            "contact_flag": "sum",
            "earliest_time": "min",
            "latest_time": "max"
        })

        # filter
        valid_df = user_df.loc[
            (user_df["comments_requested"] == 0) &
            (user_df["contact_flag"] == 0) &
            (user_df["count"] > f["request_count"]) &
            (current_timestamp - user_df["earliest_time"] > to_seconds(f["earliest_request"])) &
            (current_timestamp - user_df["latest_time"] > to_seconds(f["latest_request"]))
        ]

        valid_user_count = len(valid_df)

        self.stdout.write(
            self.style.SUCCESS(
                f"{valid_user_count} valid users found for contact within past {f['n_days']} days with at least {f['request_count']} requests, earliest request at least {f['earliest_request']} days ago, and latest request at least {f['latest_request']} days ago."
            )
        )

        valid_df.reset_index(drop=True, inplace=True)

        email = GeoEmail(None)

        # send list of users to staff emails
        if not options["dry-run"] and options["mode"] == "manual" and valid_user_count > 0:

            email_list = valid_df["email"].tolist()
            email_list_str = "\n\t".join(email_list)

            mail_to = "geo@aiddata.org, info@aiddata.org, eteare@aiddata.wm.edu"

            mail_subject = ("Your weekly list of GeoQuery user emails")

            mail_message = (
                """
                Hello there team!

                Below you will find the list of users who satisfy the criteria for contact. For details
                on what these criteria actually are, contact your GeoQuery Admin. At the end of this email
                is some sample language for contacting users.

                --------------------
                {}
                --------------------

                Hello there!

                We would like to hear about your experience using AidData's GeoQuery tool. Would you
                please respond to this email with a couple sentences about how GeoQuery has helped you?

                We are able to make GeoQuery freely available thanks to the generosity of donors and
                open source data providers. These people love to hear about new research enabled by
                GeoQuery, and what kind of difference this research is making in the world.

                Also, we love feedback of all kinds. If something did not go the way you expected, we
                want to hear about that too.

                Thanks!
                \tAidData's GeoQuery Team
                """).format(email_list_str)


            mail_message = textwrap.dedent(mail_message)

            mail_status = email.send_email(mail_to, mail_subject, mail_message)

            if not mail_status[0]:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error sending email to staff for manual contact. Error message: {mail_status[1]}"
                    )
                )
                raise mail_status[2]


        # email any users who pass above filtering with request for comments
        # add "comments_requested" = 1 flag to all of their existing requests
        for ix, user_info in valid_df.iterrows():

            user_email = user_info["email"]

            if options["mode"] == "auto" and ix >= options["email_limit"]:
                self.stdout.write(
                    self.style.WARNING(
                        "\n Warning: maximum emails reached. Exiting."
                    )
                )
                break

            self.stdout.write(
                self.style.INFO(
                    f'\t{ix}: {user_email}'
                )
            )

            # automated request for comments
            if not options["dry-run"] and options["mode"] == "auto":

                self.stdout.write(
                    self.style.INFO(
                        "sending emails..."
                    )
                )

                # avoid gmail email per second limits
                time.sleep(1)


                user_mail_subject = ("Was GeoQuery{0} helpful?").format(self.dev)

                user_mail_message = (
                    """
                    Hello there!

                    We would like to hear about your experience using AidData's GeoQuery tool. Would you
                    please respond to this email with a couple sentences about how GeoQuery has helped you?

                    We are able to make GeoQuery freely available thanks to the generosity of donors and
                    open source data providers. These people love to hear about new research enabled by
                    GeoQuery, and what kind of difference this research is making in the world.

                    Also, we love feedback of all kinds. If something did not go the way you expected, we
                    want to hear about that too.

                    Thanks!
                    \tAidData's GeoQuery Team
                    """
                )
                user_mail_message = textwrap.dedent(user_mail_message)

                mail_status = email.send_email(user_email, user_mail_subject, user_mail_message)

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE requests
                        SET comments_requested = 1
                        WHERE contact = %s
                        """,
                        [user_email],
                    )

            # flag as being included in list for staff to manually email
            elif not options["dry-run"] and options["mode"] == "manual":

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE requests
                        SET contact_flag = 1
                        WHERE contact = %s
                        """,
                        [user_email],
                    )


        self.stdout.write(
            self.style.SUCCESS(
                f"""
                ---------------------------------------
                Finished checking requests"
                {time.strftime('%Y-%m-%d  %H:%M:%S', time.localtime())}
                ---------------------------------------
                """
            )
        )
