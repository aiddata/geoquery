
import shapely

from utils.db.conn import get_conn


def get_feat_by_id(fid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """SELECT geom FROM feature_geom WHERE fid = %s""", (fid,)
            geom = cur.execute(query).fetchone()
            feat = shapely.wkb.loads(geom, hex=True)

    return feat


def get_dataset_resource_path_by_id(drid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """SELECT path FROM dataset_resources WHERE drid = %s""", (drid,)
            path = cur.execute(query).fetchone()
    return path
