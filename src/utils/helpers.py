
import shapely

from utils.db.conn import get_conn



def _get_dataset_resource_path_by_id(drid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """SELECT path FROM dataset_resources WHERE drid = %s""", (drid,)
            path = cur.execute(query).fetchone()
    return path


def _get_feat_geom_by_id(id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """SELECT shape FROM features WHERE id = %s"""
            geom = cur.execute(query, (id,)).fetchone()
            feat = shapely.wkb.loads(geom["shape"], hex=True)

    return feat


def _get_dataset_extent_by_id(id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """SELECT spatial_extent FROM datasets WHERE id = %s"""
            extent = cur.execute(query, (id,)).fetchone()
            feat = shapely.wkb.loads(extent["spatial_extent"], hex=True)

    return feat


def _get_coverage_records(status=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            coverage_query = "SELECT * FROM coverage"
            if status is not None:
                coverage_query += " WHERE status = %s" % status
            cur.execute(coverage_query)
            coverage = cur.fetchall()
            return coverage


def _update_coverage_status(geom_id, dataset_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE coverage
                SET status = %s
                WHERE geom_id = %s AND dataset_id = %s;
                """,
                (status, geom_id, dataset_id)
            )
            conn.commit()


def _get_feature_ids():
    with get_conn() as conn:
        with conn.cursor() as cur:
            feature_query = "SELECT id FROM features"
            cur.execute(feature_query)
            feature_ids = cur.fetchall()
            return feature_ids


def _get_dataset_ids():
    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_query = "SELECT id FROM datasets"
            cur.execute(dataset_query)
            dataset_ids = cur.fetchall()
            return dataset_ids

def _insert_coverage_records(coverage_list):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for c in coverage_list:
                cur.execute(
                    """
                    INSERT INTO coverage (geom_id, dataset_id, status)
                    VALUES (%s, %s, %s);
                    """,
                    (c.geom_id, c.dataset_id, c.status)
                )
            conn.commit()
