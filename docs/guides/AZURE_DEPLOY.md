# Azure Hosting (Recommended: Docker + Azure Web App for Containers)

## Why this path

- Fastest setup for your Streamlit app
- Easy redeploys after code updates
- Supports environment variables for API credentials/settings

## 1) Prerequisites

- Azure CLI installed
- Logged in: `az login`
- Docker available locally OR use `az acr build` (no local Docker needed)

## 2) Create Azure resources

```bash
RG=rg-worldquant-alpha
LOC=eastus
PLAN=plan-worldquant-alpha
APP=worldquant-alpha-lab-<unique>
ACR=acrworldquantalpha<unique>
IMG=worldquant-alpha-lab:v1

az group create -n $RG -l $LOC
az acr create -n $ACR -g $RG --sku Basic
az appservice plan create -n $PLAN -g $RG --is-linux --sku B1
az webapp create -n $APP -g $RG -p $PLAN --deployment-container-image-name $ACR.azurecr.io/$IMG
```

## 3) Build and push container image

Use ACR cloud build (recommended):

```bash
az acr build -r $ACR -t $IMG .
```

## 4) Configure Web App container image

```bash
az webapp config container set \
  -g $RG -n $APP \
  --container-image-name $ACR.azurecr.io/$IMG \
  --container-registry-url https://$ACR.azurecr.io
```

## 5) Let Web App pull from ACR

```bash
APP_ID=$(az webapp identity assign -g $RG -n $APP --query principalId -o tsv)
ACR_ID=$(az acr show -n $ACR -g $RG --query id -o tsv)
az role assignment create --assignee $APP_ID --scope $ACR_ID --role AcrPull
```

## 6) Set app environment variables

Set at least these:

```bash
az webapp config appsettings set -g $RG -n $APP --settings \
  WEBSITES_PORT=8000 \
  WQ_BASE_URL=https://api.worldquantbrain.com \
  WQ_EMAIL=<your_email> \
  WQ_PASSWORD=<your_password> \
  WQ_AUTH_PATH=/authentication \
  WQ_AUTH_CHECK_PATH=/authentication \
  WQ_SIMULATIONS_PATH=/simulations \
  WQ_SIMULATION_RESULT_TEMPLATE=/simulations/{id} \
  WQ_ALPHA_RESULT_TEMPLATE=/alphas/{id}
```

## 7) Restart and open app

```bash
az webapp restart -g $RG -n $APP
az webapp browse -g $RG -n $APP
```

## Update deployment

```bash
az acr build -r $ACR -t $IMG .
az webapp restart -g $RG -n $APP
```

## Notes

- If you hit API rate-limits, lower parallel workers in the app UI.
- Use a strong unique app and ACR name (globally unique requirements).
