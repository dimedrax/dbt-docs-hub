"""Reborn DataOps Platform — dbt docs Metadata Indexer.

Loop forever:
  1. List project prefixes in MinIO bucket dbt-docs/.
  2. Sync each project's static assets to /usr/share/nginx/html/<project>/.
  3. Render nginx.conf from the Jinja2 template (one location block per project).
  4. Touch a flag watched by the Web Server entrypoint to trigger reload.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from jinja2 import Environment, FileSystemLoader, select_autoescape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] indexer: %(message)s")
log = logging.getLogger("indexer")

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "dbt-docs")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))

DOCS_ROOT = Path(os.environ.get("DOCS_ROOT", "/usr/share/nginx/html"))
NGINX_CONF_OUT = Path(os.environ.get("NGINX_CONF_OUT", "/etc/nginx/conf.d/portal.conf"))
NGINX_RELOAD_SIGNAL_FILE = Path(
    os.environ.get("NGINX_RELOAD_SIGNAL_FILE", "/var/run/nginx/reload.flag")
)
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
FILTERING_API_UPSTREAM = os.environ.get(
    "FILTERING_API_UPSTREAM", "http://dbtdocs-filtering-api:8000"
)

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def list_projects(client) -> list[str]:
    """Return the unique list of top-level prefixes (project names)."""
    paginator = client.get_paginator("list_objects_v2")
    projects: set[str] = set()
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []) or []:
            projects.add(cp["Prefix"].rstrip("/"))
    return sorted(projects)


def sync_project(client, project: str) -> dict[str, Any]:
    """Download all objects under project/ and return metadata.

    Layout written to disk:
      <project>/manifest.json, catalog.json   <- consumed by Filtering API
      <project>/_dbt/<everything else>        <- dbt-docs native SPA
                                                  (consumed by the lineage iframe)
    """
    base = DOCS_ROOT / project
    dbt_native = base / "_dbt"
    dbt_native.mkdir(parents=True, exist_ok=True)
    paginator = client.get_paginator("list_objects_v2")
    last_modified = None
    n = 0
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Prefix=f"{project}/"):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            rel = key[len(project) + 1 :]
            if not rel:
                continue
            # manifest/catalog stay at the project root (consumed by the
            # Filtering API to apply OPA filtering before serving them to
            # the Reborn SPA). We ALSO drop a copy under _dbt/ so the
            # native dbt-docs SPA (loaded inside the lineage iframe) finds
            # them via the relative fetch it does at boot time.
            if rel in {"manifest.json", "catalog.json"}:
                primary = base / rel
                primary.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(MINIO_BUCKET, key, str(primary))
                mirror = dbt_native / rel
                mirror.write_bytes(primary.read_bytes())
            else:
                # everything else (index.html + dbt assets) goes under _dbt/
                dest = dbt_native / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(MINIO_BUCKET, key, str(dest))
            n += 1
            lm = obj["LastModified"]
            if last_modified is None or lm > last_modified:
                last_modified = lm
    log.info("synced %d objects for project %s", n, project)
    return {"objects": n, "last_modified": last_modified.isoformat() if last_modified else None}


def _humanize_age(iso_or_none: str | None) -> str:
    """Turn an ISO timestamp into a short human string for the navbar badge."""
    if not iso_or_none:
        return "—"
    try:
        ts = datetime.fromisoformat(iso_or_none.replace("Z", "+00:00"))
    except Exception:
        return iso_or_none
    delta = datetime.now(UTC) - ts
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 86400 * 30:
        return f"{s // 86400}d ago"
    return ts.strftime("%Y-%m-%d")


def render_nginx_conf(projects_meta: list[dict[str, Any]]) -> str:
    """Render nginx.conf with one location block per project, including
    metadata used by the sub_filter navbar (objects + last_modified_human)."""
    template = env.get_template("nginx.conf.j2")
    enriched = [
        {
            "name": p["name"],
            "objects": p.get("objects", 0),
            "last_modified_human": _humanize_age(p.get("last_modified")),
        }
        for p in projects_meta
    ]
    return template.render(projects=enriched, filtering_api_upstream=FILTERING_API_UPSTREAM)


def install_static_assets() -> None:
    """Copy the React SPA shells into the docs root.

    - index.html   : home page (project list, search)
    - catalog.html : per-project SPA (BrowserRouter, served on /<project>/*)
    """
    for name in ("index.html", "catalog.html"):
        src = STATIC_DIR / name
        if not src.exists():
            log.warning("Static %s not found at %s", name, src)
            continue
        dst = DOCS_ROOT / name
        dst.write_bytes(src.read_bytes())


def reload_nginx() -> None:
    """Touch the reload flag file. Web Server entrypoint watches it."""
    NGINX_RELOAD_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    NGINX_RELOAD_SIGNAL_FILE.touch()
    log.info("Reload flag touched at %s", NGINX_RELOAD_SIGNAL_FILE)


def cycle() -> None:
    try:
        client = s3()
        projects = list_projects(client)
        log.info("Detected projects: %s", projects)
    except Exception as exc:
        log.error("MinIO listing failed: %s — skipping cycle", exc)
        return

    projects_meta = []
    for p in projects:
        try:
            meta = sync_project(client, p)
        except Exception as exc:
            log.error("Failed to sync project %s: %s", p, exc)
            continue
        projects_meta.append({"name": p, **meta})

    NGINX_CONF_OUT.parent.mkdir(parents=True, exist_ok=True)
    NGINX_CONF_OUT.write_text(render_nginx_conf(projects_meta))
    install_static_assets()

    reload_nginx()
    log.info("Cycle complete — %d projects", len(projects_meta))


def main() -> None:
    log.info("Indexer starting (interval=%ds, bucket=%s)", SYNC_INTERVAL, MINIO_BUCKET)
    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        log.info("Signal %s received — exiting after current cycle", signum)
        stop = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while not stop:
        cycle()
        for _ in range(SYNC_INTERVAL):
            if stop:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
