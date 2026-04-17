# Security Policy

## Supported Scope

This repository is intended for private use and controlled deployment.
Security hardening focuses on:

- GitHub Actions CI/CD pipeline
- Azure Web App container deployment
- Secret handling for API and deployment credentials
- Optional app-level authentication

## Reporting a Vulnerability

If you discover a vulnerability, do not open a public issue with exploit details.

Use one of these private channels:

- GitHub private security advisory (preferred)
- Direct contact with repository owner

Include:

- Affected file/component
- Reproduction steps
- Impact assessment
- Suggested mitigation

## Security Baseline

Current baseline controls:

- CI deploys from `main` only
- Deployment concurrency control enabled
- Least-privilege workflow permission (`contents: read`)
- Secrets stored in GitHub Actions Secrets
- App settings stored in Azure App Service environment variables
- Optional app login gate controlled by env vars (`APP_AUTH_*`)

## Secret Management Rules

- Never commit `.env`
- Rotate these secrets periodically:
  - `ACR_PASSWORD`
  - `AZURE_WEBAPP_PUBLISH_PROFILE`
  - `WQ_PASSWORD`
  - `APP_AUTH_PASSWORD`
- Remove unused legacy secrets (for example `AZURE_CREDENTIALS`) if not in use
- Use unique secrets per environment

## Authentication Guidance

For production-like environments:

- Set `APP_AUTH_ENABLED=1`
- Configure strong values for `APP_AUTH_USERNAME` and `APP_AUTH_PASSWORD`
- Restrict App Service access where possible (IP restrictions, access control)
- Prefer secure secret stores for long-term production operations

## Operational Hardening Recommendations

- Enable branch protection on `main`
- Require pull request reviews for workflow changes
- Restrict who can edit GitHub Actions secrets/variables
- Enable GitHub secret scanning and Dependabot alerts
- Keep base container and Python dependencies updated
