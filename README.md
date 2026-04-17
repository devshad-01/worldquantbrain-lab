# WorldQuant BRAIN Lab — Deployment Runbook (Clean Config)

This is the **working** deployment setup for this project.
Use this as your repeatable checklist for future app deployments.

## What this repo deploys

- App: Streamlit app (`streamlit_app.py`)
- Container: Docker image pushed to Azure Container Registry (ACR)
- Host: Azure Web App for Containers
- CI/CD: GitHub Actions workflow (`.github/workflows/azure-cicd.yml`)

---

## Final working CI/CD approach

After many auth/subscription issues, the stable path is:

1. Build + push image to ACR using Docker login credentials
2. Deploy to Azure Web App using **publish profile** (`azure/webapps-deploy`)
3. Keep app settings configured in Azure Portal (one-time), not in CI

Professional hardening included:

- Concurrency-controlled production deployments
- Job timeout and least-privilege GitHub Actions permissions
- Optional in-app authentication gate (`APP_AUTH_*`)

This avoids brittle Azure CLI subscription context issues in CI.

---

## Required GitHub Repository Variables

Set in: `Settings -> Secrets and variables -> Actions -> Variables`

- `AZURE_RESOURCE_GROUP` = `worldquant`
- `AZURE_WEBAPP_NAME` = `worldquant-alpha-lab-shad01`
- `AZURE_CONTAINER_REGISTRY` = `quantlab`
- `AZURE_IMAGE_NAME` = `worldquant-alpha-lab`

> Keep names exact (case-sensitive).

---

## Required GitHub Repository Secrets

Set in: `Settings -> Secrets and variables -> Actions -> Secrets`

### Deployment secrets

- `ACR_USERNAME`
- `ACR_PASSWORD`
- `AZURE_WEBAPP_PUBLISH_PROFILE`

### App runtime secrets

- `WQ_BASE_URL`
- `WQ_EMAIL`
- `WQ_PASSWORD`
- `WQ_AUTH_PATH`
- `WQ_AUTH_CHECK_PATH`
- `WQ_SIMULATIONS_PATH`
- `WQ_SIMULATION_RESULT_TEMPLATE`
- `WQ_ALPHA_RESULT_TEMPLATE`

### Optional app authentication secrets (recommended)

- `APP_AUTH_ENABLED` (App Service env var, set to `1` to enable)
- `APP_AUTH_USERNAME` (App Service env var)
- `APP_AUTH_PASSWORD` (App Service env var)

---

## Where to get deployment secrets

### 1) `ACR_USERNAME` and `ACR_PASSWORD`

Azure Portal:

1. Open ACR: `quantlab`
2. Go to `Access keys`
3. Enable `Admin user`
4. Copy username + password into GitHub secrets

### 2) `AZURE_WEBAPP_PUBLISH_PROFILE`

Azure Portal:

1. Open App Service: `worldquant-alpha-lab-shad01`
2. Click `Download publish profile`
3. Open downloaded file
4. Copy **entire XML** into GitHub secret `AZURE_WEBAPP_PUBLISH_PROFILE`

---

## Trigger deployment

- Push to `main`, or
- Go to GitHub Actions and run `Azure CI/CD` manually

Expected successful flow:

1. Checkout
2. Validate Python files
3. Syntax check
4. Resolve deployment variables
5. Login to ACR
6. Build and push image
7. Deploy container to Web App
8. Show app URL

---

## One-time App Service settings (manual)

Because the current CI path uses publish profile deployment only, set these in Azure once:

Azure Portal -> App Service (`worldquant-alpha-lab-shad01`) -> `Settings -> Environment variables`

- `WEBSITES_PORT=8000`
- `WQ_BASE_URL`
- `WQ_EMAIL`
- `WQ_PASSWORD`
- `WQ_AUTH_PATH`
- `WQ_AUTH_CHECK_PATH`
- `WQ_SIMULATIONS_PATH`
- `WQ_SIMULATION_RESULT_TEMPLATE`
- `WQ_ALPHA_RESULT_TEMPLATE`

Optional auth controls:

- `APP_AUTH_ENABLED=1`
- `APP_AUTH_USERNAME=<secure-username>`
- `APP_AUTH_PASSWORD=<strong-password>`

After saving, restart the app once.

---

## Known pitfalls (we hit these)

1. **Old workflow run confusion**
   - Symptom: logs show old step like `az acr login --subscription ...`
   - Fix: trigger a fresh run on latest `main` commit.

2. **Multiline secret shell parsing**
   - Symptom: false "missing secret" for publish profile
   - Cause: shell `test -n` checks against multiline XML
   - Fix: removed brittle shell secret check step.

3. **OIDC subscription lookup errors**
   - Symptom: `Subscription ... not found`
   - Resolution used: switched deployment path to publish-profile + ACR credentials.

4. **Wrong resource group variable**
   - Must be `worldquant` for this environment.

---

## Optional cleanup (recommended)

If you stay on publish-profile deployment:

- You can keep OIDC variables/secrets, but they are not required by current workflow.
- Remove unused legacy items if you want to reduce confusion:
  - `AZURE_CREDENTIALS`
  - Any legacy endpoint variables not used by workflow

---

## Security and governance checklist

- Enable branch protection on `main`
- Require PR reviews for workflow changes
- Restrict access to Actions secrets and variables
- Rotate publish profile and ACR credentials periodically
- Keep `APP_AUTH_ENABLED=1` for internet-exposed deployments
- Review `SECURITY.md` for incident/reporting process

---

## Quick preflight checklist for next app

Before first deploy:

- [ ] ACR exists and admin user enabled
- [ ] Web App exists and can run container
- [ ] Repo variables set (`RG`, `WEBAPP`, `ACR`, `IMAGE`)
- [ ] Repo secrets set (`ACR_USERNAME`, `ACR_PASSWORD`, `AZURE_WEBAPP_PUBLISH_PROFILE`)
- [ ] App runtime secrets set (`WQ_*`)
- [ ] Workflow is latest from `main`

---

## Useful files in this repo

- `.github/workflows/azure-cicd.yml` — active deployment pipeline
- `SECURITY.md` — security policy and operational guidance
- `docs/guides/AZURE_DEPLOY.md` — Azure hosting notes
- `docs/guides/CICD_SETUP.md` — setup steps and context
- `docs/guides/STREAMLIT_QUICKSTART.md` — local app run instructions
- `docs/reference/WorldQuant BRAINOperations.md` — reference notes

---

## Project structure

- `streamlit_app.py` — main app entrypoint
- `worldquant_api_starter.py` — API helper client
- `alpha_tuner.py` — tuning utilities
- `.github/workflows/azure-cicd.yml` — deployment workflow
- `docs/guides/` — deployment and setup guides
- `docs/reference/` — reference documentation

---

If deployment fails again, first share:

1. Failing step name
2. Full error block for that step
3. Current run commit SHA

That is enough to debug fast.
