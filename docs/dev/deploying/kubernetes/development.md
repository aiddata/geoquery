# Deployment

This guide will walk you through installing the GeoQuery backend on a Kubernetes cluster.

## Dependencies
- podman 4+
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)
- [helm](https://helm.sh/docs/intro/install/)

## Spinning up a Development Cluster

If you'd like to run the GeoQuery backend on a local development cluster rather than a pre-existing cluster, follow these steps to set up a cluster with kind and podman.
Docker should work in place of podman if you prefer, refer to the [kind documentation](https://kind.sigs.k8s.io/) for guidance in setting that up.

You need to [increase inotify resource limits](https://kind.sigs.k8s.io/docs/user/known-issues/#pod-errors-due-to-too-many-open-files) on your host machine to avoid CrashLoopBackOff errors when spinning up prometheus or cnpg in kind/podman.
```
sudo sysctl fs.inotify.max_user_watches=524288
sudo sysctl fs.inotify.max_user_instances=512
```

If there was already a kind cluster running, delete it
```
kind delete cluster
```

`cd` to the `k8s` directory of this repository
```
cd k8s
```

Create the kind cluster
```
KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --config ./dev/kind-config.yaml
# only need to setup persistent volumes once when setting up cluster
kubectl apply -f ./helm_chart/static/pv.yaml
```

### Known Issues
- When using kind/podman, the inotify resource limits as described above
- If the kind cluster has been running for a long time, some containers will start crashing.
  Try deleting and re-installing the cluster if this continues to occur.

## Installing 

Install Prometheus onto the cluster
```
kubectl create namespace prometheus
kubectl config set-context --current --namespace=prometheus

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# TODO: what namespace is best to install this in? geoquery, or maybe prometheus?
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack --values prometheus-values.yaml
```

Install the cnpg operator
```
# install cnpg plugin for kubectl
# https://cloudnative-pg.io/documentation/1.20/kubectl-plugin
curl -sSfL https://github.com/cloudnative-pg/cloudnative-pg/raw/main/hack/install-cnpg-plugin.sh |  sudo sh -s -- -b /usr/local/bin

# create cnpg-system namespace
kubectl create namespace cnpg-system
kubectl config set-context --current --namespace=cnpg-system

# install helm from local
# based on helm chart from https://github.com/cloudnative-pg/charts/tree/main
git clone git@github.com:cloudnative-pg/charts.git
# reset to specific commit
# TODO: control this automatically as a git submodule
cd charts
git reset --hard 42ab86f7be5d65df87ae03cce255e8ff6a1905a7
cd ../

# install cnpg operator into cnpg-system namespace
helm upgrade --install cnpg --namespace cnpg-system charts/charts/cloudnative-pg  --set-json='monitoring.podMonitorEnabled=true'

# alternative: install helm from repo
# helm repo add cnpg https://cloudnative-pg.github.io/charts
# helm upgrade --install cnpg --namespace cnpg-system cnpg/cloudnative-pg
```

Prepare to install the GeoQuery helm chart
```

kubectl create namespace geoquery
kubectl config set-context --current --namespace=geoquery

helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm dependency build ./helm_chart
```

See the next page, Helm Chart, for instructions for configuring and installing the helm chart itself.

## Convenience Functions

### Accessing Grafana

Dump the grafana admin password (default username is "admin")
```
kubectl get secret gq-grafana -o jsonpath='{.data.admin-password}' | base64 --decode
```

Forward grafana to http://localhost:3000
```
# remove the & at the end if you want to keep this process in the foreground
kubectl port-forward service/gq-grafana 3000:80 &
```

# PostgreSQL

```
kubectl exec -ti postgis-cluster-1 -- psql geoquery
update extract_tasks set status=0;truncate extract_data;
```

```
kubectl exec --stdin --tty extract-dask-cluster-default-worker-25fb20cd2d  -- /bin/bash
```

Important to use this if running live tests with local code on python pod
```
# note that the workbench pod is only available if dev mode is on
kubectl exec --stdin --tty workbench -- /bin/bash
pip install -e /tmp/geoquery-update
```

```
kubectl get pods --all-namespaces -o jsonpath='{range .items[?(@.spec.serviceAccountName == "default")]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' 2>/dev/null
```

```
helm dependency update ./helm_chart/
helm upgrade gq ./helm_chart/ -f ./helm_chart/my_values.yaml
```

Delete everything in Kubernetes (defaults to current namespace)
```
kubectl delete all --all
```

