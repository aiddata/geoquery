from time import time, sleep
from kubernetes import client, config

from init_pg_tables import init_db
from init_pg_views import init_views

if __name__ == "__main__":
    config.load_incluster_config()

    custom_object_client = client.CustomObjectsApi()

    while True:
        cluster_phase = custom_object_client.get_namespaced_custom_object_status(group="postgresql.cnpg.io", version="v1", plural="clusters", namespace="geoquery", name="postgis-cluster")["status"]["phase"]
        if cluster_phase == "Cluster in healthy state":
            print("cluster is ready")
            break
        else:
            print(f"cluster not yet ready (phase is \"{cluster_phase}\")")
        # elif too much time has elapsed (five minutes?)
            # raise RuntimeError
        sleep(5)

    print("initializing...")
    init_db(False)
    init_views()
