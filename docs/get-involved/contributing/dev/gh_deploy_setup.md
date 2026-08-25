
# Creating a Personal Access Token for GitHub Actions Deployment

You need one secret — DEPLOY_TOKEN — added to the aiddata/geoquery repo. The GITHUB_TOKEN that Actions gets automatically only has write access to the repo the workflow runs in, so you need a token that can also push to aiddata/helm-charts and aiddata/nova-fluxcd.

1. Create a Fine-Grained PAT

Go to: github.com → your profile → Settings → Developer Settings → Personal access tokens → Fine-grained tokens → Generate new token

Fill it in:

Token name: geoquery-deploy-bot (or whatever)
Expiration: set something reasonable (90 days, 1 year)
Resource owner: aiddata (the org, not your personal account)
Repository access: select Only select repositories → pick aiddata/helm-charts and aiddata/nova-fluxcd
Permissions: under Repository permissions, set Contents → Read and write — everything else can stay None
Generate and copy the token (you only see it once).

If aiddata is an org, the token request will need to be approved by an org owner before it activates. Check Settings → Personal access tokens in the org settings to approve it.

2. Add the secret to the geoquery repo

Go to: github.com/aiddata/geoquery → Settings → Secrets and variables → Actions → New repository secret

Name: DEPLOY_TOKEN
Value: paste the token
Save it
