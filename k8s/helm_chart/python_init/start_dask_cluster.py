from dask_kubernetes.operator import KubeCluster

cluster = KubeCluster(name="extract-dask-cluster", n_workers=3, env={}, shutdown_on_close=True)
