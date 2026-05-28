# Helm Chart

The helm chart located at `/k8s/helm_chart` includes the resource definitions required to deploy the GeoQuery backend on Kubernetes.

## values.yaml

Below are some of the most important variables in `values.yaml` that should be overriden during deployment.
In-line documentation provides more detailed information about what each variable does and how it can be customized.

!!! note
    TODO

## Installing

`cd` to the `k8s` directory in this repository if you haven't already
```sh
cd k8s
```

Install the helm chart
```
# using --atomic is probably good for production startup script,
# but not necessary if we run locally and confirm that everything should be expect to install/work
helm upgrade --install gq --namespace geoquery  ./helm_chart -f ./helm_chart/my_values.yaml
```
