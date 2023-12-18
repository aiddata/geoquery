

import distributed
from dask_kubernetes.operator import KubeCluster

cluster = KubeCluster(
    name="my-dask-cluster2",
    n_workers=4,
)

cluster.adapt(4, 32)
client = distributed.Client(cluster)


import dask.array as da

arr = da.random.normal(size=(4096, 16384, 4096), chunks=(128, 512, 512)).astype('float32')
arr_slice = arr[0].compute()
