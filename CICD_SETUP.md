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

## Part B — Let GitHub talk to Azure

You need one Azure credential secret called `AZURE_CREDENTIALS`.

### 1) Create a Service Principal from terminal

Run this on your machine (must have Azure CLI and be logged in):

```bash
az login

SUB_ID=$(az account show --query id -o tsv)
RG=rg-worldquant-alpha

az ad sp create-for-rbac \
	--name "github-worldquant-cicd" \
	--role contributor \
	--scopes /subscriptions/$SUB_ID/resourceGroups/$RG \
	--sdk-auth
```

It prints JSON. **Copy all of it**.

### 2) Save that JSON in GitHub Secret

1. Open your repo: `https://github.com/devshad-01/worldquantbrain-lab`
2. Go to **Settings**
3. Go to **Secrets and variables** -> **Actions**
4. In **Secrets** tab, click **New repository secret**
5. Name: `AZURE_CREDENTIALS`
6. Paste JSON from previous step
7. Save

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

- **Workflow fails at Azure login** -> `AZURE_CREDENTIALS` JSON is wrong/missing
- **Container pull fails** -> ACR name variable wrong or AcrPull role missing
- **App starts but errors inside** -> missing `WQ_*` secrets
- **Too many 429 API errors** -> reduce workers in app UI to 2 or 3

