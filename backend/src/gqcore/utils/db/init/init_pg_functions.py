"""Module providing functions to initialize views in PostgreSQL."""

from loguru import logger

from gqcore.utils.db.conn import get_conn


def create_function_feature_collection_geoms():
    """Create the coverage_with_dependencies view."""
    query = """
        CREATE OR REPLACE
            FUNCTION feature_collection_geoms(z integer, x integer, y integer, query_params json)
            RETURNS bytea AS $$
        DECLARE
        mvt bytea;
        BEGIN
        SELECT INTO mvt ST_AsMVT(tile, 'feature_collection_geoms', 4096, 'geom') FROM (
            SELECT shape FROM features
        ) as tile;

        RETURN mvt;
        END
        $$ LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            logger.info("created function feature_collection_geoms")


def init_functions():
    """
    Create all functions.
    """
    logger.info("creating functions...")
    create_function_feature_collection_geoms()


if __name__ == "__main__":
    init_functions()
