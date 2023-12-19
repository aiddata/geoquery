kind delete cluster
cd k8s

KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --config ./dev/kind-config.yaml


# ------------------
# postgis operator setup

# install cnpg plugin
# https://cloudnative-pg.io/documentation/1.20/kubectl-plugin
curl -sSfL https://github.com/cloudnative-pg/cloudnative-pg/raw/main/hack/install-cnpg-plugin.sh |  sudo sh -s -- -b /usr/local/bin

kubectl create namespace cnpg-system
kubectl config set-context --current --namespace=cnpg-system

# install helm from local
# based on helm chart from https://github.com/cloudnative-pg/charts/tree/main
git clone git@github.com:cloudnative-pg/charts.git
helm upgrade --install cnpg --namespace cnpg-system charts/charts/cloudnative-pg

# alternative: install helm from repo
# helm repo add cnpg https://cloudnative-pg.github.io/charts
# helm upgrade --install cnpg --namespace cnpg-system cnpg/cloudnative-pg


# ------------------
# main geoquery (with dask operator) setup

kubectl create namespace geoquery
kubectl config set-context --current --namespace=geoquery

helm repo add dask https://helm.dask.org/
helm repo update

helm dependency build ./helm_chart

# using --atomic is probably good for production startup script,
# but not necessary if we run locally and confirm that everything should be expect to install/work
helm upgrade --install gq --namespace geoquery  ./helm_chart -f ./helm_chart/my_values.yaml

# create dask operator and namespace
# helm install - geoquery     dask-kubernetes-operator    ./helm_chart     -f ./dev/values.yaml
# helm install -n geoquery --generate-name dask/dask-kubernetes-operator --set rbac.cluster=false --set kopfArgs="{--namespace=geoquery}"


# -------------------------------------
# -------------------------------------
# CONVENIENCE COMMANDS

kubectl exec -ti postgis-cluster-1 -- psql geoquery

kubectl exec --stdin --tty python -- /bin/bash
kubectl exec --stdin --tty extract-dask-cluster- -- /bin/bash

pip install -e /tmp/geoquery-update

kubectl get pods --all-namespaces -o jsonpath='{range .items[?(@.spec.serviceAccountName == "default")]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' 2>/dev/null


helm dependency update ./helm_chart/
helm upgrade gq ./helm_chart/ -f ./helm_chart/my_values.yaml


# delete everything
# default to current namespace
kubectl delete all --all
