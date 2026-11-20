---
description: "Creating and installing the DEPLOY_TOKEN secret the release workflow uses to push to aiddata/helm-charts and aiddata/nova-fluxcd."
---

# GitHub deploy token

The `Deploy GeoQuery` workflow pushes to two other repositories: the chart version and image tags to `aiddata/helm-charts`, and the pinned chart version to `aiddata/nova-fluxcd` ([Deploying with Flux](deploying/kubernetes/flux.md)). The `GITHUB_TOKEN` Actions provides can only write to the repository the workflow runs in, so the workflow uses a fine-grained personal access token stored as the `DEPLOY_TOKEN` secret.

When it expires, releases fail at the "Checkout helm-charts" step. Replace it as below.

## 1. Create the token

On GitHub, go to your profile → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**, and fill it in:

| Field | Value |
|---|---|
| Token name | `geoquery-deploy-bot`, or similar |
| Expiration | 90 days to a year; note the date |
| Resource owner | `aiddata` (the organization, not your account) |
| Repository access | **Only select repositories**: `aiddata/helm-charts` and `aiddata/nova-fluxcd` |
| Repository permissions | **Contents: Read and write**. Leave everything else at No access |

Generate it and copy it; GitHub shows it only once.

An organization owner has to approve a token for `aiddata` before it works: the organization's **Settings** → **Personal access tokens** → **Pending requests**.

## 2. Install it

In `aiddata/geoquery`, go to **Settings** → **Secrets and variables** → **Actions**, and create (or update) the repository secret `DEPLOY_TOKEN` with the token as its value.

## 3. Check it

The next release shows whether it works: its `Deploy GeoQuery` run should get past "Checkout helm-charts" and push to both repositories. (Re-running an already published release doesn't test it, because the workflow stops early when the chart version already exists with the same images.)
