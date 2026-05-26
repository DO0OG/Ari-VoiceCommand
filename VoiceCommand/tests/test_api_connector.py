import json

from agent.api_connector import ApiConnector


def test_api_connector_loads_openapi_spec(tmp_path, monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "demo"},
        "servers": [{"url": "https://example.test"}],
        "paths": {
            "/items/{item_id}": {
                "get": {
                    "operationId": "getItem",
                    "parameters": [{"name": "item_id", "in": "path", "schema": {"type": "string"}}],
                }
            }
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    connector = ApiConnector()
    tools = connector.load_openapi_spec(str(path))
    assert tools[0]["function"]["name"] == "api_demo_getItem"

    calls = {}

    class Response:
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_request(method, url, **kwargs):
        calls.update({"method": method, "url": url, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("agent.api_connector.requests.request", fake_request)
    assert "ok" in connector.call("getItem", {"item_id": "42"}, service="demo")
    assert calls["method"] == "GET"
    assert calls["url"] == "https://example.test/items/42"
