# API Contracts

`openapi.json` is generated from the FastAPI application and is the handoff
artifact for dashboard development.

Regenerate and review it after any route or public-schema change:

```bash
uv run python scripts/export_openapi.py
```

The public resource and envelope models use camelCase fields and versioned
`/api/v1` routes. Nested canonical mapping and quality contracts retain their
versioned canonical field names. Local filesystem paths and object-store URIs are
not part of reviewer or dashboard responses.
