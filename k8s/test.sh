kind delete cluster
cd k8s

KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --config ./dev/kind-config.yaml

# ------------------

kubectl create namespace geoquery
kubectl config set-context --current --namespace=geoquery

helm repo add dask https://helm.dask.org/
helm repo update

helm dependency build ./helm_chart

# create dask operator and namespace
# helm install - geoquery     dask-kubernetes-operator    ./helm_chart     -f ./dev/values.yaml
# helm install -n geoquery --generate-name dask/dask-kubernetes-operator --set rbac.cluster=false --set kopfArgs="{--namespace=geoquery}"

helm install gq --namespace geoquery  ./helm_chart


# kubectl apply -f ./helm_chart/templates/pvc.yaml
# kubectl apply -f ./helm_chart/templates/pv.yaml
# kubectl apply -f ./helm_chart/templates/rbac.yaml
# kubectl apply -f ./helm_chart/templates/python.yaml

# kubectl create configmap postgis-cluster-rw-config --from-literal=POSTGRES=postgis-cluster-rw.cnpg-system.svc.cluster.local


# ------------------
# postgis
# for h

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


# kubectl config set-context --current --namespace=geoquery

# kubectl apply -f ./helm_chart/templates/cnpg/postgis.yaml



# ------------------

kubectl exec -ti postgis-cluster-1 -- psql geoquery

kubectl exec --stdin --tty python2 -- /bin/bash

pip install -e /tmp/geoquery-update

kubectl get pods --all-namespaces -o jsonpath='{range .items[?(@.spec.serviceAccountName == "default")]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' 2>/dev/null


# ------------------
helm dependency update ./helm_chart/
helm upgrade gq ./helm_chart/
