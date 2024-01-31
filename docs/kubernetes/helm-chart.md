# Helm Chart

The helm chart located at `/k8s/helm_chart` includes the resource definitions required to deploy the GeoQuery backend on Kubernetes.

## values.yaml

Below are some of the most important variables in `values.yaml` that should be overriden during deployment.
In-line documentation provides more detailed information about what each variable does and how it can be customized.

!!! note
    TODO

## Installing

```sh
cd k8s
helm upgrade --install gq --namespace geoquery  ./helm_chart -f ./helm_chart/my_values.yaml
```
