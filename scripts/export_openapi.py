"""Export the FastAPI OpenAPI spec to docs/openapi.json and docs/openapi.yaml.

Usage (from dove-engine/):  python scripts/export_openapi.py
Does not need Postgres/MQTT: the app lifespan is not run.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APP_ENV", "test")

from app.main import app  # noqa: E402

spec = app.openapi()
out = ROOT / "docs"
out.mkdir(exist_ok=True)
(out / "openapi.json").write_text(json.dumps(spec, indent=2) + "\n")

try:
    import yaml
    (out / "openapi.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))
except ImportError:
    print("pyyaml not installed; skipped openapi.yaml")

print(f"Wrote {len(spec['paths'])} paths to {out}")
