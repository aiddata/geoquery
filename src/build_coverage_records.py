
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Json, ValidationInfo, field_validator
from shapely import wkb

from utils.db.conn import get_conn

valid_status_dict = {
    -1: "not checked",
    0: "no coverage",
    1: "coverage",
}


class CoverageRecord(BaseModel):
    geom_id: int
    dataset_id: int
    status: Optional[int] = -1

    @field_validator("status")
    @classmethod
    def validate_statusn(cls, s: int) -> int:
        if s not in valid_status_dict:
            raise ValueError(
                "status must be one of the following: {}".format(valid_status_dict)
            )
        return s


def generate_coverage_records():
    with get_conn() as conn:
        with conn.cursor() as cur:
            existing_coverage_query = "SELECT * FROM coverage"
            cur.execute(existing_coverage_query)
            existing_coverage = cur.fetchall()
            existing_items = [(x["geom_id"], x["dataset_id"]) for x in existing_coverage]

    with get_conn() as conn:
        with conn.cursor() as cur:
            feature_query = "SELECT id FROM features"
            cur.execute(feature_query)
            features = cur.fetchall()
            if len(features) == 0:
                raise ValueError("No features found in database")

    with get_conn() as conn:
        with conn.cursor() as cur:
            dataset_query = "SELECT id FROM datasets"
            cur.execute(dataset_query)
            datasets = cur.fetchall()
            if len(datasets) == 0:
                raise ValueError("No datasets found in database")


    potential_coverage = list(zip(features, datasets))

    new_coverage = [
        CoverageRecord(**{"geom_id":x[0]["id"], "dataset_id":x[1]["id"]}) for x in potential_coverage
        if (x[0]["id"], x[1]["id"]) not in existing_items
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for c in new_coverage:
                cur.execute(
                    """
                    INSERT INTO coverage (geom_id, dataset_id, status)
                    VALUES (%s, %s, %s);
                    """,
                    (c.geom_id, c.dataset_id, c.status)
                )

            conn.commit()


def test_coverage():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM coverage WHERE status = -1")
            coverage_items = cur.fetchall()

    for c in coverage_items:
        feature_id = c["geom_id"]
        dataset_id = c["dataset_id"]

        with get_conn() as conn:
            with conn.cursor() as cur:
                feature_data = cur.execute(
                    "SELECT * FROM features WHERE id = %s", (feature_id,)
                ).fetchone()

        with get_conn() as conn:
            with conn.cursor() as cur:
                dataset_data = cur.execute(
                    "SELECT * FROM datasets WHERE id = %s", (dataset_id,)
                ).fetchone()


        # load geoms as wkbs
        feature_geom_wkb = feature_data["shape"]
        dataset_spatial_extent_wkb = dataset_data["spatial_extent"]

        # convert wkb to shapely geometry
        feature_geom = wkb.loads(feature_geom_wkb, hex=True)
        dataset_spatial_extent = wkb.loads(dataset_spatial_extent_wkb, hex=True)

        # compare feature geom to dataset spatial_extent
        # if feature geom is within dataset spatial_extent, set coverage to 1
        # else set coverage to 0

        if feature_geom.within(dataset_spatial_extent):
            new_status = 1
        else:
            new_status = 0

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coverage
                    SET status = %s
                    WHERE geom_id = %s AND dataset_id = %s;
                    """,
                    (new_status, feature_id, dataset_id)
                )

if __name__ == "__main__":
    generate_coverage_records()
    test_coverage()
