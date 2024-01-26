from time import sleep, time

from init_pg_tables import init_db
from init_pg_views import init_views
from kubernetes import client, config

from gqcore.utils.logs import get_logger


@logger.catch(reraise=True)
def init_db_when_ready() -> None:
    # we will be connecting to the k8s API from within a container
    # which has been given a serviceaccount
    config.load_incluster_config()

    # a cnpg cluster (database) is considered a custom object,
    # so we will need a CustomObjectsApi to retrieve info about it
    custom_object_client = client.CustomObjectsApi()

    while True:
        # get status "phase" string for database (cnpg cluster)
        cluster_phase = custom_object_client.get_namespaced_custom_object_status(
            group="postgresql.cnpg.io",
            version="v1",
            plural="clusters",
            namespace="geoquery",
            name="postgis-cluster",
        )["status"]["phase"]

        # is the database (cnpg cluster) fully up and ready?
        # TODO: investigate better options for testing db readiness beyond a string comparison
        if cluster_phase == "Cluster in healthy state":
            logger.info("database is ready to initialize")
            break
        else:
            logger.info(
                f'database is not yet ready to initialize (phase is "{cluster_phase}")'
            )
        # elif too much time has elapsed (make this configurable with values.yaml?)
        # logger.critical("database creation timeout exceeded, canceling db init")
        sleep(5)

    logger.info("initializing database...")
    # create tables
    init_db(False)
    # create views
    init_views()
    logger.info("finished initializing database.")


if __name__ == "__main__":
    get_logger("init_database")
    init_db_when_ready()
