# New Taipei Youth Policy — AWS workstream targets.
# Run `make help` for the full list. Targets marked (creds) need AWS credentials.

ENV ?= dev
DEST ?= ./exports/aws

.DEFAULT_GOAL := help

.PHONY: help demo-features agent-evals local-api dashboard hackathon-bootstrap aws-preflight aws-synth aws-smoke \
        aws-export aws-teardown test lint typecheck format

help:  ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*## "} {printf "  %-22s %s\n", $$1, $$2}'

local-api:  ## Run the offline FastAPI service on port 8000
	uv run uvicorn apps.api.main:app --reload --port 8000

dashboard:  ## Run the temporary Streamlit dashboard on port 8501
	uv run streamlit run apps/dashboard/app.py --server.port 8501

demo-features:  ## Materialize an offline feature snapshot for the copilot demo
	uv run python -m scripts.materialize_demo_features

agent-evals:  ## Grade planning and answers offline (routing + answer suites)
	uv run python -m scripts.run_agent_evals --suite all

hackathon-bootstrap:  ## Empty account to verified stack (creds). ASSUME_YES=1 to skip prompt
	uv run python -m scripts.aws_bootstrap $(if $(ASSUME_YES),--assume-yes,)

aws-preflight:  ## Ten-second account-readiness check (creds)
	uv run python -m scripts.aws_preflight

aws-synth:  ## Synthesize CDK templates, no deploy. Set ENV=dev|demo|hackathon
	cd infra && uv run cdk synth -c env=$(ENV) -c budgetEmail=$${YOUTH_COMPASS_BUDGET_EMAIL:-alerts@example.invalid}

aws-smoke:  ## Round-trip smoke test in Moto mode (free, no creds)
	uv run python -m scripts.aws_smoke_test

aws-export:  ## Export S3 and Glue data locally (creds). Set DEST=./path
	uv run python -m scripts.aws_export --dest $(DEST)

aws-teardown:  ## Destroy deployed stacks after account-number confirm (creds)
	uv run python -m scripts.aws_teardown

test:  ## Run the full test suite with coverage
	uv run pytest --cov=youth_compass --cov-report=term-missing

lint:  ## Ruff check and format check
	uv run ruff check .
	uv run ruff format --check src apps tests scripts

typecheck:  ## Strict mypy over source, apps, scripts, and infra
	uv run mypy src apps scripts
	uv run mypy infra

format:  ## Reformat and autofix
	uv run ruff format src apps tests scripts
	uv run ruff check . --fix

build-api-lambda:  ## Build the API Lambda deployment package
	uv run python scripts/build_lambda.py api

deploy-api:  ## Build and deploy the API + static site stack (creds)
	uv run python scripts/build_lambda.py api
	cd infra && npx --yes aws-cdk@2 deploy \
		"YouthCompass-$(ENV)-Workflow" "YouthCompass-$(ENV)-Api" \
		-c env=$(ENV) -c region=$${YOUTH_COMPASS_REGION:-us-east-1} \
		-c account=$${AWS_ACCOUNT_ID} -c withApi=1 \
		-c budgetEmail=$${YOUTH_COMPASS_BUDGET_EMAIL:-alerts@example.invalid} \
		--require-approval never

deploy-site:  ## Upload web/ to the site bucket and invalidate CloudFront (creds)
	uv run python -m scripts.deploy_site

bedrock-check:  ## Probe which Bedrock models this account can actually invoke (creds)
	uv run python -m scripts.bedrock_check --region $${YOUTH_COMPASS_REGION:-us-east-1}
