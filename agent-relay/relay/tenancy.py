"""Tenant keys: every request for a tenant's memory must carry that tenant's key.

A key is an HMAC of the tenant name with a server secret, so the server can check it without storing keys, and a key
for one tenant can't be turned into a key for another. The secret is RELAY_TENANT_SECRET, or derived from the database
password when that isn't set (so a deployment needs no extra secret). Keys are never logged.
"""
import hashlib
import hmac
import os

from . import config

_SECRET = (os.environ.get("RELAY_TENANT_SECRET")
           or hashlib.sha256(f"relay-tenant-keys:{config.FALKOR_PASS or 'local-dev'}".encode()).hexdigest()).encode()
DEMO_KEYS = os.environ.get("RELAY_DEMO_KEYS", "1") != "0"  # the demo hands keys to its own web app; production doesn't
ADMIN = "__operator__"


def key_for(tenant):
    return "tk_" + hmac.new(_SECRET, f"tenant:{tenant}".encode(), hashlib.sha256).hexdigest()[:32]


def owner(key, tenants):
    """Which of these tenants a key belongs to (None if it's no tenant's key)."""
    return next((t for t in tenants if key and hmac.compare_digest(key, key_for(t))), None)


def check(tenant, key):
    """None if the key opens this tenant, else the reason it doesn't (for a 401/403)."""
    if not key:
        return "missing"
    return None if hmac.compare_digest(key, key_for(tenant)) else "wrong"


if __name__ == "__main__":  # self-check
    a, b = key_for("pml"), key_for("pml-eu")
    assert a != b and check("pml", a) is None and check("pml", b) == "wrong" and check("pml", "") == "missing"
    assert check("pml", a[:-1] + ("0" if a[-1] != "0" else "1")) == "wrong" and owner(b, ["pml", "pml-eu"]) == "pml-eu"
    print("tenancy self-check ok")
