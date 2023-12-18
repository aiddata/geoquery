from dask.distributed import Client
from dask_kubernetes.operator import KubeCluster

cluster = KubeCluster.from_name("extract-dask-cluster")

cluster.scale(2)

client = Client(cluster)
