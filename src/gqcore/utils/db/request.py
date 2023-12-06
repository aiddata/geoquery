import itertools
from datetime import datetime
from typing import List, Tuple
import textwrap
import os
from pathlib import Path
import shutil

from pydantic import BaseModel, Json, field_validator
import pandas as pd
import shapely
import geopandas as gpd

from gqcore.utils.db.conn import get_conn
from gqcore.utils.email import GeoEmail
from gqcore import get_config
from gqcore.utils.documentation import DocBuilder


class Request(BaseModel):
    source: str
    contact: str
    custom_name: str
    info: str
    priority: int = 1
    data: List[List[int]] # each item in list is a list containing resource_id, feature_id, processing_option_id

    @field_validator("priority")
    @classmethod
    def function_must_exist(cls, p: int) -> int:
        if p < 0:
            raise ValueError("request priority must be at least 1")
        return p



def insert_request(request: Request):
    params = request.model_dump()
    params["date"] = datetime.now()
    params["status"] = -1

    with get_conn() as conn:
        with conn.cursor() as cur:
            # build request query and insert it

            insert_request_query = """
                INSERT INTO requests (
                    date,
                    source,
                    contact,
                    custom_name,
                    info,
                    priority,
                    status
                ) VALUES (
                    %(date)s,
                    %(source)s,
                    %(contact)s,
                    %(custom_name)s,
                    %(info)s,
                    %(priority)s,
                    %(status)s

                ) RETURNING id;
            """

            cur.execute(insert_request_query, params)

            # get request id that was just inserted

            request_id = cur.fetchone()["id"]

            params_list = []
            for i in request.data:
                extract_task_item = dict(zip(["resource_id", "feature_id", "processing_option_id"], i))
                extract_task_item["priority"] = request.priority
                params_list.append(extract_task_item)


            insert_extract_task_query = """
                INSERT INTO extract_tasks (
                    resource_id,
                    fm_id,
                    po_id,
                    priority
                ) VALUES (
                    %(resource_id)s,
                    %(feature_id)s,
                    %(processing_option_id)s,
                    %(priority)s
                )
                ON CONFLICT (resource_id, fm_id, po_id)
                DO UPDATE SET priority = %(priority)s
                RETURNING id;
            """

            cur.executemany(insert_extract_task_query, params_list, returning=True)
            extract_task_ids = []
            while True:
                extract_task_ids.append(cur.fetchone()["id"])
                if not cur.nextset():
                    break

            insert_request_map_query = """
                INSERT INTO request_map (
                    req_id,
                    task_id
                ) VALUES (
                    %s,
                    %s
                );
            """
            cur.executemany(
                insert_request_map_query, [(request_id, i) for i in extract_task_ids], returning=True
            )

def process_new_requests():
    while True:
        request_info = get_next_new_request()
        if not request_info:
            break
        request_id = request_info["request_id"]
        request_contact = request_info["contact"]
        update_request_time(request_id, "prepare_time")
        update_request_status(request_id, 0)
        notify_received(request_id, request_contact)


def get_next_new_request():
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    requests.id as request_id,
                    requests.contact as contact
                FROM requests
                WHERE status = -1
                LIMIT 1
                """
            cur.execute(query)
            result = cur.fetchone()
            return result


def process_completed_requests():
    config = get_config()
    data_root = Path(config["main"]["data_root"])

    while True:
        request_id, request_contact, request_df = get_next_completed_request()
        if not request_df:
            break

        update_request_time(request_id, "process_time")

        output_df = build_output_df(request_df)

        output_dir = data_root / "data" / "outputs" / str(request_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "data.csv"
        output_df.to_csv(output_path, index=False)

        doc_output =  output_dir / "documentation.pdf"
        build_request_documentation(request_id, request_df, doc_output)

        fc_gdf = build_feature_collection(request_df[["geom", "geom_id"]].drop_duplicates("geom_id").copy())
        for geomtype in fc_gdf.geom_type.unique():
            fc_gdf[fc_gdf.geom_type == geomtype].to_file(output_dir / "features.gpkg", driver="GPKG", layer=geomtype)

        build_request_zip(request_id, output_dir)

        # update with complete time
        update_request_time(request_id, "complete_time")

        update_request_status(request_id, 1)

        notify_completed(request_id, request_contact)


def update_request_time(request_id, time_type):
    with get_conn() as conn:
        with conn.cursor() as cur:
            update_time_query = """
                UPDATE requests
                SET {0} = %s
                WHERE id = %s
            """.format(time_type)
            cur.execute(update_time_query, (datetime.now(), request_id))


def get_next_completed_request():
    with get_conn() as conn:
        with conn.cursor() as cur:
            id_query = """
            SELECT *
            FROM (
                SELECT
                    requests.id as request_id,
                    sum(CASE WHEN (extract_tasks.status = 1) THEN 1 ELSE 0 END) AS completed,
                    count(extract_tasks.status) AS total
                FROM requests
                JOIN request_map
                    ON requests.id = request_map.req_id
                JOIN extract_tasks
                    ON request_map.task_id = extract_tasks.id
                WHERE requests.status = 0
                GROUP BY requests.id
            )
            JOIN requests ON request_id = requests.id
            JOIN request_map ON requests.id = request_map.req_id
            JOIN extract_tasks ON request_map.task_id = extract_tasks.id
            WHERE completed = total
            ORDER BY requests.priority DESC, requests.submit_time ASC
            LIMIT 1
            """
            cur.execute(id_query)
            result = cur.fetchone()
            if not result:
                return None, None, None
            request_id = result["request_id"]
            request_contact = result["contact"]
            data_query = """
                SELECT
                    extract_tasks.fm_id as fm_id,
                    extract_tasks.resource_id as resource_id,
                    extract_tasks.po_id as po_id,
                    extract_data.name as data_name,
                    extract_data.data_column as data_column,
                    extract_data.int_value as int_value,
                    extract_data.str_value as str_value,
                    extract_data.float_value as float_value,
                    feat_map.name as name,
                    feat_map.attr as attr,
                    features.shape as geom,
                    features.id as geom_id,
                    dataset_resources.name as resource_name,
                    dataset_resources.label as resource_label,
                    datasets.name as dataset_name
                FROM (
                    SELECT * FROM request_map
                    WHERE req_id = %s
                )
                AS request_map
                LEFT OUTER JOIN extract_tasks
                    ON task_id = extract_tasks.id
                LEFT OUTER JOIN extract_data
                    ON task_id = extract_data.id
                LEFT OUTER JOIN feat_map
                    ON extract_tasks.fm_id = feat_map.id
                LEFT OUTER JOIN features
                    ON feat_map.geom_id = features.id
                LEFT OUTER JOIN dataset_resources
                    ON extract_tasks.resource_id = dataset_resources.id
                LEFT OUTER JOIN datasets
                    ON dataset_resources.dataset_id = datasets.id
            """
            cur.execute(data_query, (request_id,))
            request_info = cur.fetchall()
            request_df = pd.DataFrame(request_info)
            return request_id, request_contact, request_df


def build_output_df(request_df):
    # for each request, build a results table
    # consiting of all the extract_data associated with the extract_task for the request

    request_df["col_name"] = request_df["dataset_name"] + "." + request_df["resource_label"] + "." + request_df["data_name"]
    df = request_df.pivot(index="fm_id", columns=["col_name"], values='int_value').reset_index()

    attr_df = request_df[["fm_id", "name", "attr"]].drop_duplicates("fm_id")
    attr_df.loc[attr_df.fm_id == 2, "attr"] = [{"test": "test"}]
    attr_df = attr_df.join(attr_df.attr.apply(pd.Series))
    attr_df = attr_df.drop(columns=["attr"])

    df = df.merge(attr_df, on="fm_id")

    return df


def build_request_documentation(request_id, request_df, doc_output):
    doc = DocBuilder(request_id, request_df, doc_output)
    bd_status = doc.build_doc()


def build_request_zip(request_id, output_dir):
    assets_dir = output_dir.parent.parent.parent / "src/gqcore/assets"

    geo_pdf_src = assets_dir / "other" / "GeoQuery_Goodman2019_compressed.pdf"
    geo_pdf_dst = output_dir / "GeoQuery_Goodman2019.pdf"
    shutil.copyfile(geo_pdf_src, geo_pdf_dst)

    zip_dst = output_dir.parent / f"{request_id}"
    shutil.make_archive(zip_dst, "zip", output_dir)

    # delete pdf from output dir so it's not wasting space after zip is created
    os.remove(geo_pdf_dst)

    return zip_dst


def build_feature_collection(feature_df):
    # read geom from wkb
    feature_df["geometry"] = feature_df["geom"].apply(lambda x: shapely.wkb.loads(x, hex=True))
    feature_df["id"] = feature_df["geom_id"]
    feature_gdf = gpd.GeoDataFrame(feature_df[["id", "geometry"]], geometry="geometry")
    feature_gdf.crs = "EPSG:4326"
    return feature_gdf


def update_request_status(request_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            update_request_status_query = """
                UPDATE requests
                SET status = %s
                WHERE id = %s
            """
            cur.execute(update_request_status_query, (status, request_id))


def notify_received(request_id, request_contact):
    """send email that request was received
    """
    request_id = str(request_id)

    config = get_config()
    devtag = config["other"]["devtag"]
    request_url = config["other"]["request_url"]

    mail_to = request_contact

    mail_subject = ("AidData GeoQuery{0}- "
                    "Request {1}.. Received").format(devtag, request_id[:7])

    mail_message = (
        """
        Thanks for using GeoQuery. This is an automated email to let you
        know that we received your request and will process your data as
        soon as we can. We will send another email when your data is ready. \n

        You can view the status of this data request here:
        http://{0}/query/#!/status/{1}          \n

        You can also keep track of all of the data requests that you've
        submitted with this email address here:
        http://{0}/query/#!/requests/{2}        \n

        Thank you,
        \tAidData's GeoQuery Team
        """).format(request_url, request_id, mail_to)

    mail_message = textwrap.dedent(mail_message)

    GE = GeoEmail()
    try:
        mail_status = GE.send_email(mail_to, mail_subject, mail_message)
    except Exception as e:
        print(e)
        update_request_status(request_id, -2)
        raise e


def notify_completed(request_id, request_contact):
    """send email that request was completed
    """
    request_id = str(request_id)

    config = get_config()
    devtag = config["other"]["devtag"]
    request_url = config["other"]["request_url"]

    mail_to = request_contact

    mail_subject = ("AidData GeoQuery{0}- "
                    "Request {1}.. Completed").format(devtag, request_id[:7])

    mail_message = (
        """
        Thanks again for using GeoQuery. This is another automated email to let you know that
        your data is ready. \n

        You can review your request, and download the results and documentation here:
        \thttp://{0}/query/#!/status/{1}    \n

        Or download the results directly (this link will always be available):
        \thttp://{0}/data/geoquery_results/{1}/{1}.zip  \n

        You can also view all your current and previous requests using:
        \thttp://{0}/query/#!/requests/{2}  \n

        Also, one quick reminder about citations. Don't forget to cite both AidData's GeoQuery
        tool as well as each dataset you selected within GeoQuery. All citations can be found
        in the Documentation PDF at the link above. Here's the correct citation for GeoQuery:   \n

            Goodman, S., BenYishay, A., Lv, Z., & Runfola, D. (2019).
            GeoQuery: Integrating HPC systems and public web-based
            geospatial data tools. Computers & Geosciences, 122, 103-112.   \n

        Thank you in advance for citing us when you publish your research.
        This helps us to demonstrate how GeoQuery is making a difference
        as a freely available public good.  \n

        Thank you,
        \tAidData's GeoQuery Team
        """).format(request_url, request_id, mail_to)

    mail_message = textwrap.dedent(mail_message)

    GE = GeoEmail()
    try:
        mail_status = GE.send_email(mail_to, mail_subject, mail_message)
    except Exception as e:
        print(e)
        update_request_status(request_id, -2)
        raise e



# if __name__ == "__main__":
#     request = Request(**{
#         "source": "script",
#         "contact": "sgoodman@aiddata.wm.edu",
#         "custom_name": "test1",
#         "info": "Nothing1",
#         "data": [[1, 1, 1], [1, 2, 1], [1, 3, 1], [1, 4, 1],
#                  [2, 1, 1], [2, 2, 1], [2, 3, 1], [2, 4, 1]],
#     })
#     insert_request(request)

#     request = Request(**{
#         "source": "script",
#         "contact": "sgoodman@aiddata.wm.edu",
#         "custom_name": "test2",
#         "info": "Nothing2",
#         "data": [[1, 11, 1], [1, 12, 1]],
#     })
#     insert_request(request)
