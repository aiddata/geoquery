from datetime import datetime
import textwrap
import os
from pathlib import Path
import shutil

import pandas as pd
import shapely
import geopandas as gpd
from loguru import logger

from gqcore.utils.db.conn import get_conn
from gqcore.utils.email import GeoEmail
from gqcore import get_config
from gqcore.utils.documentation import DocBuilder


@logger.catch(reraise=True)
def process_new_requests():
    while True:
        request_info = get_next_new_request()
        if not request_info:
            break
        request_id = request_info["request_id"]

        rlogger = logger.bind(request_id=str(request_id)[:8])
        rlogger.info("Processing new request")

        request_contact = request_info["contact"]
        update_request_time(request_id, "prepare_time")
        update_request_status(request_id, 0)

        rlogger.info("Sending email")
        notify_received(request_id, request_contact)

        rlogger.success("New request processed")



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


@logger.catch(reraise=True)
def process_completed_requests():
    config = get_config()
    data_root = Path(config["main"]["data_root"])

    while True:
        request_id, request_contact, request_df = get_next_completed_request()
        if request_df is None:
            break
        rlogger = logger.bind(request_id=str(request_id)[:8])
        logger.info("Processing completed request")

        update_request_time(request_id, "process_time")

        rlogger.debug("Building output data")
        output_df = build_output_df(request_df)

        output_dir = data_root / "data" / "outputs" / str(request_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "data.csv"
        output_df.to_csv(output_path, index=False)

        rlogger.debug("Building documentation")
        doc_output =  output_dir / "documentation.pdf"
        build_request_documentation(request_id, request_df, doc_output)

        rlogger.debug("Building feature collection")
        fc_gdf = build_feature_collection(request_df[["geom", "geom_id"]].drop_duplicates("geom_id").copy())
        for geomtype in fc_gdf.geom_type.unique():
            fc_gdf[fc_gdf.geom_type == geomtype].to_file(output_dir / "features.gpkg", driver="GPKG", layer=geomtype)

        rlogger.debug("Building zip")
        build_request_zip(request_id, output_dir)

        # update with complete time
        update_request_time(request_id, "complete_time")

        update_request_status(request_id, 1)

        rlogger.debug("Sending email")
        notify_completed(request_id, request_contact)

        rlogger.success("Completed request processed")


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
                    datasets.name as dataset_name,
                    processing_options.short_name as po_name,
                    processing_options.description as po_description,
                    processing_options.result_type as po_result_type
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
                LEFT OUTER JOIN processing_options
                    ON extract_tasks.po_id = processing_options.id
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
