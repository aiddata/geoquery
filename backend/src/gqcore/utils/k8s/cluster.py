from time import sleep

from kubernetes import client, config
from loguru import logger

from gqcore import get_config


# TODO: add timeout kwarg
@logger.catch(reraise=True)
def wait_for_db() -> None:

    gqcore_config = get_config()

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
            namespace=gqcore_config["namespace"],
            name="postgis-cluster",
        )["status"]["phase"]

        # is the database (cnpg cluster) fully up and ready?
        # TODO: investigate better options for testing db readiness beyond a string comparison
        if cluster_phase == "Cluster in healthy state":
            logger.info("database is now ready")
            break
        else:
            logger.info(f'database is not yet ready (phase is "{cluster_phase}")')
        # elif too much time has elapsed (make this configurable with values.yaml?)
        # logger.critical("database creation timeout exceeded, canceling db init")
        sleep(5)


# TODO: add timeout kwarg
@logger.catch(reraise=True)
def wait_for_init() -> bool:
    # we will be connecting to the k8s API from within a container
    # which has been given a serviceaccount
    config.load_incluster_config()

    # get client to watch job
    client_batch_api = client.BatchV1Api()

    while True:
        # if job completed successfully
        if client_batch_api.read_namespaced_job_status(
            "geoguery-init-db", "geoquery"
        ).status.succeeded:
            logger.info("init db job succeeded!")
            return True
        # elif job is no longer active (not pending or running)
        elif not client_batch_api.read_namespaced_job_status(
            "geoguery-init-db", "geoquery"
        ).status.active:
            logger.warning("init db job didn't succeed, and it's no longer active!")
            return False
        # else if timeout exceeded, quit

        sleep(5)
