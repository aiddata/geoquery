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


kubectl config set-context --current --namespace=geoquery

kubectl apply -f ./helm_chart/templates/cnpg/postgis.yaml

kubectl exec -ti postgis-cluster-1 -- psql geoquery


# ------------------




# # pg operator
# # https://github.com/zalando/postgres-operator/blob/master/docs/quickstart.md/

# # add repo for postgres-operator
# helm repo add postgres-operator-charts https://opensource.zalando.com/postgres-operator/charts/postgres-operator

# # install the postgres-operator
# helm install postgres-operator postgres-operator-charts/postgres-operator

# # add repo for postgres-operator-ui
# helm repo add postgres-operator-ui-charts https://opensource.zalando.com/postgres-operator/charts/postgres-operator-ui

# # install the postgres-operator-ui
# helm install postgres-operator-ui postgres-operator-ui-charts/postgres-operator-ui

# kubectl apply -f ./helm_chart/templates/pg_op/manifest.yaml

# kubectl exec -it acid-test-cluster-  --  psql -h localhost -U zolando --password -p 5432 postgresdb



# # kubectl apply -f ./helm_chart/templates/pg/config_map.yaml
# # kubectl apply -f ./helm_chart/templates/pg/vols.yaml
# # kubectl apply -f ./helm_chart/templates/pg/deployment.yaml
# # kubectl apply -f ./helm_chart/templates/pg/service.yaml
# kubectl exec -it acid-minimal-cluster-0   --  psql -h localhost -U zolando -p 5432


# kubectl exec -it postgis-6965f455df-pmr8k  --  psql -h localhost -U admin --password -p 5432 postgresdb
# kubectl exec --stdin --tty postgis-6965f455df-pmr8k -- /bin/bash



kubectl exec --stdin --tty python -- /bin/bash

pip install -e /tmp/geoquery-update

import psycopg
x = psycopg.connect("postgresql://geoquery:dante@postgis-cluster3-rw.geoquery.svc.cluster.local:5432")

# helm install my-daskhub dask/daskhub --version 2023.1.0

# helm install my-dask dask/dask --version 2023.1.0

# kubectl logs <pod_name>
