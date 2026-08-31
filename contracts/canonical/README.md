# Canonical Contracts

The JSON Schema files in this directory are generated from the Pydantic source models.

Regenerate them with:

```bash
uv run python scripts/export_contracts.py
```

Do not edit generated schema files manually. Review schema diffs whenever a Pydantic contract changes.
