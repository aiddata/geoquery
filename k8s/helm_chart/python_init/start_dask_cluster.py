from dask.distributed import Client, PipInstall
from distributed.diagnostics.plugin import UploadDirectory
from dask_kubernetes.operator import KubeCluster


# cluster = KubeCluster(
#     name="extract-dask-cluster",
#     n_workers=3,
#     # env={"EXTRA_PIP_PACKAGES": "dask"},
#     # image="",
#     shutdown_on_close=False,
# )

# HelmCluster vs DaskCluster (and adaptivity)
# https://github.com/dask/dask-kubernetes/issues/277

cluster = KubeCluster.from_name("extract-dask-cluster")
client = Client(cluster)

client.register_plugin(UploadDirectory("/tmp/geoquery-update/src"))

package_list = ["shapely", "loguru", "psycopg", "pydantic", "typing_extensions", "dask_kubernetes", "dask[distributed]"]
plugin = PipInstall(packages=package_list)
client.register_plugin(plugin)

def install():
    import os
    os.system("pip install /tmp/dask-scratch-space/geoquery-update")

client.run(install)
