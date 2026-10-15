"""Tests talk to the API like the web app does: with the tenant's key on every tenant request."""
import re

from fastapi.testclient import TestClient

from relay import tenancy

_request = TestClient.request
_ws = TestClient.websocket_connect


def _request_with_key(self, method, url, *args, headers=None, **kw):
    m = re.match(r"(?:https?://[^/]+)?/api/tenants/([^/?]+)", str(url))
    if m and not (headers and "x-tenant-key" in {k.lower() for k in headers}):
        headers = {**(headers or {}), "X-Tenant-Key": tenancy.key_for(m.group(1))}
    if re.match(r"(?:https?://[^/]+)?/api/isolation", str(url)):
        headers = {**(headers or {}), "X-Admin-Key": tenancy.key_for(tenancy.ADMIN)}
    return _request(self, method, url, *args, headers=headers, **kw)


def _ws_with_key(self, url, *args, **kw):
    m = re.match(r"/ws/([^/?]+)$", str(url))
    return _ws(self, f"{url}?key={tenancy.key_for(m.group(1))}" if m else url, *args, **kw)


TestClient.request = _request_with_key
TestClient.websocket_connect = _ws_with_key
