"""Export only the routes actually implemented by the current application."""

import json
from pathlib import Path

from app.main import app

path = Path(__file__).resolve().parents[1] / "contracts" / "demo.openapi.json"
path.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("Exported implemented demo and guest API")
