# Deploying with Flux

Production runs on Kubernetes, reconciled by [FluxCD](https://fluxcd.io). You do
not deploy by running `helm` or `kubectl apply` — you merge a commit with a
release marker and the pipeline does the rest.

## Triggering a release

Put `[DEPLOY-X.Y.Z]` in a commit message on `main`:

```
git commit -m "Fix the thing [DEPLOY-0.45.12]"
```

`X.Y.Z` becomes the Helm chart version, so it must be **higher than the last
release** — the chart repository will not replace an existing version. Check
what is live first:

```bash
kubectl get helmrelease geoquery-prod -n aiddata \
  -o jsonpath='{.status.lastAttemptedRevision}'
```

Commits without a marker build images but deploy nothing, which is the normal
case for most merges.

## What actually happens

The pipeline spans **three repositories**. Knowing this matters, because a
failure in any of them looks the same from the application repo.

| # | Where | What happens |
|---|---|---|
| 1 | `aiddata/geoquery` | Build workflows produce `geoquery-backend` / `geoquery-frontend` images tagged with the commit SHA |
| 2 | `aiddata/geoquery` | `Deploy GeoQuery` reads the marker and resolves the image SHAs |
| 3 | `aiddata/helm-charts` | It commits the new `version:` into `Chart.yaml` and the image tags into `values.yaml` |
| 4 | `aiddata/helm-charts` | `Release Charts` publishes the chart to GitHub Pages (`aiddata.github.io/helm-charts`) |
| 5 | `aiddata/nova-fluxcd` | The deploy workflow bumps the chart version in the environment overlay |
| 6 | cluster | Flux notices, runs a Helm upgrade, which runs the migration Job, then rolls the Deployments |

End to end this takes **roughly 15 minutes**, most of it waiting on the GitHub
Pages build (step 4) and Flux's reconcile intervals (step 6).

## Verifying it landed

The authoritative check is the cluster, not the workflow run:

```bash
# chart version Flux is trying to apply
kubectl get helmrelease geoquery-prod -n aiddata -o jsonpath='{.status.lastAttemptedRevision}'

# image actually running
kubectl get deploy geoquery-backend -n geoquery-prod \
  -o jsonpath='{.spec.template.spec.containers[0].image}'

# did the rollout finish
kubectl rollout status deploy/geoquery-backend -n geoquery-prod
```

Expect chart version to move first, then the image a minute or two later.

## Failure modes

These have all happened. None of them is obvious from a green workflow run.

### The deploy workflow succeeds without deploying

`Deploy GeoQuery` resolves each image's SHA by querying the Actions API. If that
lookup fails it prints `ERROR: no successful '<workflow>' run found`, writes
`skip=true`, and **exits 0** — so `gh run list` shows success and nothing is
deployed.

Seen once from a transient API failure (the same query succeeded minutes later
by hand). Symptom: the workflow run is suspiciously short (~8 s) and the chart
version never moves.

```bash
gh run view <run-id> --log | grep -E "Build (backend|frontend) container:|no successful"
```

Re-run the workflow to recover: `gh run rerun <run-id>`.

### The release is `Stalled` after a slow migration

The chart's pre-upgrade migration Job runs `migrate`, `createcachetable` and
`ensure_mcp_oidc_client`. If it exceeds the HelmRelease's `spec.timeout`, Helm
declares the upgrade failed, and because retries are then exhausted **Flux does
not retry on its own**.

```bash
kubectl get helmrelease geoquery-prod -n aiddata \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.message}{"\n"}{end}'
```

A `Stalled=True` with `pre-upgrade hooks failed: timeout waiting for Job` means
this. Recover with a forced reconcile — a plain reconcile is not enough once
retries are exhausted:

```bash
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
kubectl annotate helmrelease geoquery-prod -n aiddata \
  "reconcile.fluxcd.io/requestedAt=$TS" "reconcile.fluxcd.io/forceAt=$TS" --overwrite
```

Check the Job's own outcome before assuming the migration failed — it often
**succeeded** and Helm simply stopped waiting first.

### The chart version is not published yet

```
invalid chart reference: no 'geoquery' chart with version matching 'X.Y.Z' found
```

Step 5 outran step 4: Flux is looking for a chart GitHub Pages has not finished
publishing (that build can take ~9 minutes). It resolves itself once the index
updates and Flux re-fetches (`HelmRepository` interval). Confirm with:

```bash
curl -s https://aiddata.github.io/helm-charts/index.yaml | grep -oE "version: X\.Y\.Z"
```

### Nothing moves at all

Check that the marker parsed and that the version is actually higher than the
deployed one. A re-used or lower version silently changes nothing.

## Experimental changes to cluster settings

Flux has drift detection disabled, so a direct patch to a resource it manages
**persists until the next chart upgrade**. That makes it a reasonable way to test
a runtime-reloadable setting before committing it:

```bash
kubectl patch cluster geoquery-db -n geoquery-prod --type=merge \
  -p '{"spec":{"postgresql":{"parameters":{"commit_delay":"100"}}}}'
```

Anything permanent belongs in the chart. Anything affecting the database is
covered by [Database](../../database.md) — check it before tuning, since
several obvious levers have already been measured and rejected.
