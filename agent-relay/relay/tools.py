"""Mock back-office systems for the resolver agent. Synthetic: data/world.json, or a world set per tenant."""
import json
from functools import lru_cache

from . import config

WORLDS = {}  # tenant -> world dict (set by the simulator / demo story)


@lru_cache
def _file_world():
    path = config.ROOT / "data" / "world.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def world(tenant=None):
    return WORLDS.get(tenant) or _file_world()


def billing_plan(customer, tenant=None):
    return world(tenant).get("billing", {}).get(customer)


def outages_in(city, tenant=None, at=None):
    """Outages the feed reports for a city at time `at` (epoch ms). Entries without a window are ongoing."""
    live = lambda o: at is None or (o.get("from", 0) <= at < o.get("until", float("inf")))
    return [o["name"] for o in world(tenant).get("outages", []) if city in o["cities"] and live(o)]


def diagnostic(customer, tenant=None):
    return world(tenant).get("diagnostics", {}).get(customer)


def fix_works(customer, fix, tenant=None):
    """Whether a fix resolves this customer's problem (simulated). Unknown fixes don't work."""
    return fix in world(tenant).get("working_fixes", {}).get(customer, [])
