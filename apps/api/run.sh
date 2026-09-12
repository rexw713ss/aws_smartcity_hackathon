#!/bin/sh
exec python -m uvicorn apps.api.lambda_handler:app --host 0.0.0.0 --port 8000
