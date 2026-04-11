# CI/CD Setup (Very Simple Guide)

This project already has the workflow file:

- `.github/workflows/azure-cicd.yml`

This means: **when you push to `main`, GitHub can deploy your app to Azure automatically**.

---

## Part A — Create Azure things (click-by-click)

### 1) Open Azure Portal

1. Go to `https://portal.azure.com`
2. Log in

### 2) Create Resource Group

1. In search bar, type **Resource groups**
2. Click **Create**
3. Name: `rg-worldquant-alpha`
4. Region: choose one (example: East US)
5. Click **Review + create** -> **Create**

### 3) Create Azure Container Registry (ACR)

1. Search **Container registries**
2. Click **Create**
3. Resource group: `rg-worldquant-alpha`
4. Registry name: must be globally unique, example: `acrworldquantshad01`
5. SKU: **Basic**
6. Click **Review + create** -> **Create**

### 4) Create App Service Plan (Linux)

1. Search **App Service plans**
2. Click **Create**
3. Resource group: `rg-worldquant-alpha`
4. Name: `plan-worldquant-alpha`
5. OS: **Linux**
6. Pricing tier: **B1** (good starter)
7. Create

### 5) Create Web App (Container)

1. Search **App Services**
2. Click **Create** -> **Web App**
3. Resource group: `rg-worldquant-alpha`
4. Name: unique name, example: `worldquant-alpha-lab-shad01`
5. Publish: **Container**
6. Operating system: **Linux**
7. Region: same as above
8. App Service plan: `plan-worldquant-alpha`
9. Create

---

## Part B — Let GitHub talk to Azure (OIDC, no client secret)

This project uses **OIDC** for Azure login. You do **not** need `AZURE_CREDENTIALS`.

### 1) Create (or reuse) a Service Principal

Run this on your machine (must have Azure CLI and be logged in):

```bash
az login

SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
RG=rg-worldquant-alpha
APP_NAME=github-worldquant-cicd

az ad app create --display-name "$APP_NAME"
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
SP_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)

az role assignment create \
	--assignee-object-id "$SP_ID" \
	--assignee-principal-type ServicePrincipal \
	--role contributor \
	--scope /subscriptions/$SUB_ID/resourceGroups/$RG
```

### 2) Add federated credential for GitHub Actions

```bash
cat > federated-credential.json <<'JSON'
{
	"name": "github-main-branch",
	"issuer": "https://token.actions.githubusercontent.com",
	"subject": "repo:devshad-01/worldquantbrain-lab:ref:refs/heads/main",
	"description": "GitHub Actions OIDC for main branch",
	"audiences": ["api://AzureADTokenExchange"]
}
JSON

az ad app federated-credential create \
	--id "$APP_ID" \
	--parameters federated-credential.json
```

### 3) Save Azure identity values in GitHub Variables

1. Open repo: `https://github.com/devshad-01/worldquantbrain-lab`
2. Go to **Settings**
3. Go to **Secrets and variables** -> **Actions**
4. Open **Variables** tab and add:
   - `AZURE_CLIENT_ID` = `$APP_ID`
   - `AZURE_TENANT_ID` = `$TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID` = `$SUB_ID`

---

## Part C — Add GitHub Variables (non-secret values)

In same GitHub page, go to **Variables** tab and add:

- `AZURE_RESOURCE_GROUP` = `rg-worldquant-alpha`
- `AZURE_WEBAPP_NAME` = `worldquant-alpha-lab-shad01` (your real web app name)
- `AZURE_CONTAINER_REGISTRY` = `acrworldquantshad01` (your real ACR name)
- `AZURE_IMAGE_NAME` = `worldquant-alpha-lab`

---

## Part D — Add GitHub Secrets for app config

In **Secrets** tab, add these:

- `WQ_BASE_URL` = `https://api.worldquantbrain.com`
- `WQ_EMAIL` = your email
- `WQ_PASSWORD` = your password
- `WQ_AUTH_PATH` = `/authentication`
- `WQ_AUTH_CHECK_PATH` = `/authentication`
- `WQ_SIMULATIONS_PATH` = `/simulations`
- `WQ_SIMULATION_RESULT_TEMPLATE` = `/simulations/{id}`
- `WQ_ALPHA_RESULT_TEMPLATE` = `/alphas/{id}`

---

## Part E — Trigger deployment

### Option 1 (easy)

Push any commit to `main`.

### Option 2 (manual)

1. Repo -> **Actions**
2. Click workflow **Azure CI/CD**
3. Click **Run workflow**

---

## Part F — Check if it worked

1. In GitHub Actions, open the latest run
2. Make sure all steps are green
3. Last step prints URL like:
   - `https://<your-webapp>.azurewebsites.net`
4. Open it in browser

---

## Common mistakes (and fix)

- **Workflow fails at Azure login** -> missing/wrong `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, or missing federated credential subject
- **Container pull fails** -> ACR name variable wrong or AcrPull role missing
- **App starts but errors inside** -> missing `WQ_*` secrets
- **Too many 429 API errors** -> reduce workers in app UI to 2 or 3
