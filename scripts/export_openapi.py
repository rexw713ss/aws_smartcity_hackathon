"""Export the FastAPI OpenAPI contract for frontend development."""

import json
from pathlib import Path

from apps.api.main import app

OUTPUT = Path("contracts/api/openapi.json")


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI contract written to {OUTPUT}")


if __name__ == "__main__":
    main()
