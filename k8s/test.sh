# If you encounter CrashLoopBackOff errors when spinning up prometheus or cnpg in kind/podman,
# you likely need to increase inotify resource limits on your host computer:
# https://kind.sigs.k8s.io/docs/user/known-issues/#pod-errors-due-to-too-many-open-files
sudo sysctl fs.inotify.max_user_watches=524288
sudo sysctl fs.inotify.max_user_instances=512


kind delete cluster
cd k8s

KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster --config ./dev/kind-config.yaml

# only need to setup persistent volumes once when setting up cluster
kubectl apply -f ./helm_chart/static/pv.yaml

# ------------------
# prometheus operator setup

kubectl create namespace prometheus
kubectl config set-context --current --namespace=prometheus

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# TODO: what namespace is best to install this in? geoquery, or maybe prometheus?
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack --values prometheus-values.yaml


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
# TODO: add something to checkout/reset to specific commit? or download a release instead?
# git ...

helm upgrade --install cnpg --namespace cnpg-system charts/charts/cloudnative-pg  --set-json='monitoring.podMonitorEnabled=true'

# alternative: install helm from repo
# helm repo add cnpg https://cloudnative-pg.github.io/charts
# helm upgrade --install cnpg --namespace cnpg-system cnpg/cloudnative-pg


# ------------------
# main geoquery (with dask operator) setup

kubectl create namespace geoquery
kubectl config set-context --current --namespace=geoquery

helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm dependency build ./helm_chart

# using --atomic is probably good for production startup script,
# but not necessary if we run locally and confirm that everything should be expect to install/work
helm upgrade --install gq --namespace geoquery  ./helm_chart -f ./helm_chart/my_values.yaml
# helm install gq --namespace geoquery  ./helm_chart -f ./helm_chart/my_values.yaml

# create dask operator and namespace
# helm install - geoquery     dask-kubernetes-operator    ./helm_chart     -f ./dev/values.yaml
# helm install -n geoquery --generate-name dask/dask-kubernetes-operator --set rbac.cluster=false --set kopfArgs="{--namespace=geoquery}"


# -------------------------------------
# -------------------------------------
# CONVENIENCE COMMANDS


# dump the grafana admin password
# username is "admin"
kubectl get secret gq-grafana -o jsonpath='{.data.admin-password}' | base64 --decode

# forward grafana to http://localhost:3000
kubectl port-forward service/gq-grafana 3000:80 & # that last & sends process to background

kubectl exec -ti postgis-cluster-1 -- psql geoquery
update extract_tasks set status=0;truncate extract_data;

kubectl exec --stdin --tty extract-dask-cluster-default-worker-25fb20cd2d  -- /bin/bash

# !! important to use this if running live tests with local code on python pod
kubectl exec --stdin --tty python -- /bin/bash
pip install -e /tmp/geoquery-update

kubectl get pods --all-namespaces -o jsonpath='{range .items[?(@.spec.serviceAccountName == "default")]}{.metadata.namespace} {.metadata.name}{"\n"}{end}' 2>/dev/null


helm dependency update ./helm_chart/
helm upgrade gq ./helm_chart/ -f ./helm_chart/my_values.yaml


# delete everything
# default to current namespace
kubectl delete all --all
