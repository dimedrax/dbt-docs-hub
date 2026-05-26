"""Pytest config — make filtering_api modules importable from tests/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Default env so module-level os.environ.get() calls don't blow up at import.
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("POLICY_ENGINE_URL", "http://policy-engine.test")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
