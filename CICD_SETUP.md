# CI/CD Setup (GitHub Actions -> Azure Web App for Containers)

This repo includes workflow: `.github/workflows/azure-cicd.yml`

## 1) Create GitHub Repository Variables

Go to: **GitHub -> Settings -> Secrets and variables -> Actions -> Variables**

Add:

- `AZURE_RESOURCE_GROUP` (e.g. `rg-worldquant-alpha`)
- `AZURE_WEBAPP_NAME` (e.g. `worldquant-alpha-lab-xxxx`)
- `AZURE_CONTAINER_REGISTRY` (ACR name only, e.g. `acrworldquantalphaxxxx`)
- `AZURE_IMAGE_NAME` (e.g. `worldquant-alpha-lab`)

## 2) Create GitHub Repository Secrets

Go to: **GitHub -> Settings -> Secrets and variables -> Actions -> Secrets**

### Azure auth secret

- `AZURE_CREDENTIALS` = JSON from service principal (`az ad sp create-for-rbac ... --sdk-auth`)

### App settings secrets

- `WQ_BASE_URL` (usually `https://api.worldquantbrain.com`)
- `WQ_EMAIL`
- `WQ_PASSWORD`
- `WQ_AUTH_PATH` (usually `/authentication`)
- `WQ_AUTH_CHECK_PATH` (usually `/authentication`)
- `WQ_SIMULATIONS_PATH` (usually `/simulations`)
- `WQ_SIMULATION_RESULT_TEMPLATE` (usually `/simulations/{id}`)
- `WQ_ALPHA_RESULT_TEMPLATE` (usually `/alphas/{id}`)

## 3) Grant GitHub SP access to Azure resources

Ensure service principal in `AZURE_CREDENTIALS` has permissions on:

- Resource Group (Contributor)
- ACR (Contributor or AcrPush)
- Web App (Contributor)

## 4) Push to main or run manually

- Push to `main` triggers deployment automatically.
- Or run manually from **Actions -> Azure CI/CD -> Run workflow**.

## 5) Verify deployment

Workflow output prints deployed URL.

## Notes

- Workflow builds Docker image, pushes to ACR, updates Web App container, sets app settings, and restarts app.
- First run might take longer while image layers are created.
