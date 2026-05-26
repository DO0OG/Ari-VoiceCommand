"""OpenAPI 기반 외부 REST API 연결 프레임워크."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests


@dataclass
class ApiOperation:
    service: str
    operation: str
    method: str
    path: str
    base_url: str
    parameters: dict[str, Any] = field(default_factory=dict)


class ApiConnector:
    def __init__(self):
        self._operations: dict[tuple[str, str], ApiOperation] = {}

    def load_openapi_spec(self, spec_url_or_path: str, service: str | None = None) -> list[dict[str, Any]]:
        spec = self._load_spec(spec_url_or_path)
        service_name = service or spec.get("info", {}).get("title") or os.path.splitext(os.path.basename(spec_url_or_path))[0]
        service_name = str(service_name or "default").strip()
        servers = spec.get("servers") or []
        base_url = str((servers[0] if servers else {}).get("url", "") or "")
        tools: list[dict[str, Any]] = []
        for path, path_item in dict(spec.get("paths") or {}).items():
            for method, operation_spec in dict(path_item or {}).items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation = str(operation_spec.get("operationId") or f"{method}_{path.strip('/').replace('/', '_')}")
                params_schema = self._parameters_schema(operation_spec)
                self._operations[(service_name, operation)] = ApiOperation(
                    service=service_name,
                    operation=operation,
                    method=method.upper(),
                    path=str(path),
                    base_url=base_url,
                    parameters=params_schema,
                )
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"api_{service_name}_{operation}".replace("-", "_"),
                        "description": str(operation_spec.get("summary") or operation_spec.get("description") or operation),
                        "parameters": {"type": "object", "properties": params_schema},
                    },
                })
        return tools

    def call(self, operation_id: str, params: dict[str, Any] | None = None, service: str = "default") -> str:
        params = dict(params or {})
        op = self._operations.get((service, operation_id))
        if op is None:
            matches = [item for key, item in self._operations.items() if key[1] == operation_id]
            if len(matches) == 1:
                op = matches[0]
        if op is None:
            raise KeyError(f"등록되지 않은 API 작업: {service}.{operation_id}")
        path = op.path
        query: dict[str, Any] = {}
        for key, value in params.items():
            placeholder = "{" + key + "}"
            if placeholder in path:
                path = path.replace(placeholder, str(value))
            else:
                query[key] = value
        url = urljoin(op.base_url.rstrip("/") + "/", path.lstrip("/")) if op.base_url else path
        request_kwargs: dict[str, Any] = {"timeout": 30}
        if op.method in {"POST", "PUT", "PATCH"}:
            request_kwargs["json"] = query
        elif query:
            request_kwargs["params"] = query
        response = requests.request(op.method, url, **request_kwargs)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            return json.dumps(response.json(), ensure_ascii=False, indent=2)
        return response.text[:8000]

    def _load_spec(self, spec_url_or_path: str) -> dict[str, Any]:
        source = str(spec_url_or_path or "").strip()
        if source.startswith(("http://", "https://")):
            response = requests.get(source, timeout=30)
            response.raise_for_status()
            return response.json()
        with open(source, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _parameters_schema(self, operation_spec: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for param in operation_spec.get("parameters") or []:
            name = param.get("name")
            if not name:
                continue
            properties[str(name)] = dict(param.get("schema") or {"type": "string"})
            if param.get("description"):
                properties[str(name)]["description"] = param.get("description")
        request_body = operation_spec.get("requestBody", {})
        content = request_body.get("content", {}) if isinstance(request_body, dict) else {}
        json_schema = (content.get("application/json", {}) or {}).get("schema", {})
        if isinstance(json_schema, dict):
            properties.update(dict(json_schema.get("properties") or {}))
        return properties


_instance: ApiConnector | None = None


def get_api_connector() -> ApiConnector:
    global _instance
    if _instance is None:
        _instance = ApiConnector()
    return _instance
