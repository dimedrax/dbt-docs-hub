"""Reborn DataOps Platform — dbt docs filtering API.

Sits behind nginx. nginx serves static assets directly and only forwards
manifest.json / catalog.json requests to this app. We re-fetch the artefacts
from MinIO on every call (small JSON, cached at MinIO/proxy level), apply OPA
decisions, then return the filtered payload.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

import policy_engine
from jwt_utils import extract_groups, extract_username

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("dbtdocs")

app = FastAPI(title="Reborn — dbt docs API", version="0.1.0")

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "dbt-docs")


@lru_cache(maxsize=1)
def s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _fetch_json(project: str, filename: str) -> dict[str, Any]:
    key = f"{project}/{filename}"
    try:
        obj = s3().get_object(Bucket=MINIO_BUCKET, Key=key)
    except Exception as exc:
        log.warning("MinIO fetch failed for %s/%s: %s", MINIO_BUCKET, key, exc)
        raise HTTPException(
            status_code=404, detail=f"{filename} not found for project {project}"
        ) from exc
    return json.loads(obj["Body"].read())


def _filter_manifest(manifest: dict[str, Any], project: str, groups: list[str]) -> dict[str, Any]:
    """Strip columns the user is not allowed to see."""
    nodes = manifest.get("nodes", {})
    for node in nodes.values():
        cols = node.get("columns") or {}
        kept = {}
        for col_name, col in cols.items():
            tags = col.get("tags") or []
            if policy_engine.column_visible(groups, project, node.get("name", ""), col_name, tags):
                kept[col_name] = col
        node["columns"] = kept
    manifest["nodes"] = nodes
    return manifest


def _filter_catalog(
    catalog: dict[str, Any],
    project: str,
    groups: list[str],
    tags_by_col: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    """Catalog has no tags itself — borrow them from the manifest map."""
    nodes = catalog.get("nodes", {})
    for node in nodes.values():
        model = node.get("metadata", {}).get("name", "")
        cols = node.get("columns") or {}
        kept = {}
        for col_name, col in cols.items():
            tags = tags_by_col.get(model, {}).get(col_name, [])
            if policy_engine.column_visible(groups, project, model, col_name, tags):
                kept[col_name] = col
        node["columns"] = kept
    catalog["nodes"] = nodes
    return catalog


def _tags_index(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Build {model_name: {col_name: tags}} from a manifest."""
    out: dict[str, dict[str, list[str]]] = {}
    for node in (manifest.get("nodes") or {}).values():
        model = node.get("name")
        if not model:
            continue
        out[model] = {c: (col.get("tags") or []) for c, col in (node.get("columns") or {}).items()}
    return out


def _infer_layer(node: dict[str, Any], project: str | None = None) -> str:
    """Resolve the model 'layer' as a free-form string.

    Priority:
      1. node.meta.layer (explicit override in dbt YAML)
      2. node.schema with the project prefix stripped (e.g. 'voiture_marts'
         -> 'marts'); this is the canonical source for the POC.
      3. fallback to resource_type ('source' / 'seed' / 'model').

    The frontend assigns a colour to known names (gold/silver/bronze/source/
    marts/staging/raw/...) and falls back to a neutral grey for anything
    else, so we don't have to guess at the API level.
    """
    explicit = ((node.get("meta") or {}).get("layer") or "").strip().lower()
    if explicit:
        return explicit

    schema = (node.get("schema") or "").strip().lower()
    if schema:
        # Strip a "<project>_" prefix if present so 'voiture_marts' -> 'marts'.
        if project and schema.startswith(f"{project.lower()}_"):
            schema = schema[len(project) + 1 :]
        return schema or "model"

    rt = (node.get("resource_type") or "model").lower()
    return rt


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/{project}/models")
def list_models(project: str, request: Request) -> dict[str, Any]:
    """Return the enriched model list for a project, OPA-filtered.

    Each item: {unique_id, name, resource_type, layer, schema, description,
                tags, materialized, columns_count, pii_columns_count,
                tests_count, depends_on}
    """
    auth = request.headers.get("Authorization")
    groups = extract_groups(auth)
    user = extract_username(auth) or "anonymous"

    if not policy_engine.project_allowed(groups, project):
        raise HTTPException(status_code=403, detail=f"Access denied to project {project}")

    manifest = _fetch_json(project, "manifest.json")
    nodes = manifest.get("nodes") or {}
    sources = manifest.get("sources") or {}

    # Index tests per (model_unique_id) for the count.
    tests_by_node: dict[str, int] = {}
    for n in nodes.values():
        if n.get("resource_type") != "test":
            continue
        for dep in (n.get("depends_on") or {}).get("nodes", []) or []:
            tests_by_node[dep] = tests_by_node.get(dep, 0) + 1

    items = []
    for unique_id, node in {**nodes, **sources}.items():
        rt = node.get("resource_type", "model")
        if rt == "test":
            continue
        cols = node.get("columns") or {}
        pii_cnt = sum(1 for c in cols.values() if "pii" in (c.get("tags") or []))
        items.append(
            {
                "unique_id": unique_id,
                "name": node.get("name"),
                "resource_type": rt,
                "layer": _infer_layer(node, project),
                "schema": node.get("schema"),
                "database": node.get("database"),
                "description": node.get("description") or "",
                "tags": node.get("tags") or [],
                "materialized": (node.get("config") or {}).get("materialized") or rt,
                "columns_count": len(cols),
                "pii_columns_count": pii_cnt,
                "tests_count": tests_by_node.get(unique_id, 0),
                "depends_on": (node.get("depends_on") or {}).get("nodes", []),
                "path": node.get("path") or "",
            }
        )
    items.sort(key=lambda m: (m["resource_type"] != "model", m["layer"], m["name"] or ""))

    log.info("models for %s requested by %s -> %d items", project, user, len(items))
    return {"project": project, "user": user, "groups": groups, "models": items}


@app.get("/api/projects")
def list_projects(request: Request) -> dict[str, Any]:
    """Return projects + search index, filtered by what the caller can access."""
    auth = request.headers.get("Authorization")
    groups = extract_groups(auth)
    user = extract_username(auth) or "anonymous"

    paginator = s3().get_paginator("list_objects_v2")
    prefixes: set[str] = set()
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []) or []:
            prefixes.add(cp["Prefix"].rstrip("/"))

    projects = []
    search_index: list[dict[str, Any]] = []
    for project in sorted(prefixes):
        if not policy_engine.project_allowed(groups, project):
            continue
        try:
            manifest = _fetch_json(project, "manifest.json")
        except HTTPException:
            continue
        node_count = len(manifest.get("nodes", {}))
        last = manifest.get("metadata", {}).get("generated_at")
        projects.append(
            {
                "name": project,
                "model_count": node_count,
                "generated_at": last,
            }
        )
        for node in (manifest.get("nodes") or {}).values():
            cols = node.get("columns") or {}
            visible_cols = [
                c
                for c, col in cols.items()
                if policy_engine.column_visible(
                    groups, project, node.get("name", ""), c, col.get("tags") or []
                )
            ]
            search_index.append(
                {
                    "project": project,
                    "model": node.get("name"),
                    "schema": node.get("schema"),
                    "description": node.get("description", ""),
                    "tags": node.get("tags", []),
                    "columns": visible_cols,
                }
            )

    log.info("projects listed for %s (groups=%s) -> %d projects", user, groups, len(projects))
    return {"user": user, "groups": groups, "projects": projects, "models": search_index}


@app.get("/{project}/manifest.json")
def get_manifest(project: str, request: Request) -> JSONResponse:
    auth = request.headers.get("Authorization")
    groups = extract_groups(auth)
    user = extract_username(auth) or "anonymous"
    log.info("manifest %s requested by %s (groups=%s)", project, user, groups)

    if not policy_engine.project_allowed(groups, project):
        raise HTTPException(status_code=403, detail=f"Access denied to project {project}")

    manifest = _fetch_json(project, "manifest.json")
    filtered = _filter_manifest(manifest, project, groups)
    return JSONResponse(filtered)


@app.get("/{project}/catalog.json")
def get_catalog(project: str, request: Request) -> JSONResponse:
    auth = request.headers.get("Authorization")
    groups = extract_groups(auth)
    user = extract_username(auth) or "anonymous"
    log.info("catalog %s requested by %s (groups=%s)", project, user, groups)

    if not policy_engine.project_allowed(groups, project):
        raise HTTPException(status_code=403, detail=f"Access denied to project {project}")

    manifest = _fetch_json(project, "manifest.json")
    catalog = _fetch_json(project, "catalog.json")
    filtered = _filter_catalog(catalog, project, groups, _tags_index(manifest))
    return JSONResponse(filtered)
