"""Predicate vocabularies. Core predicates are a fixed enum (contradiction handling depends on them); anything else
concrete is an open attribute (see OPEN below).

A new domain is a new registry; the engine is unchanged. Tenants named `life-*` use LIFE, all others use ISP.
"""
import re

# predicate: (subject_type, object_type, cardinality, memory_type, conflict_policy)
# conflict_policy "trust": claims from different agents coexist and are ranked at read time.
# conflict_policy "latest": workflow state; any agent's newer write supersedes.
# Subject type "customer" = the person the conversation is with (a support customer, or a chat speaker).
ISP = {
    "lives_in":        ("customer", "city",    "single", "semantic",     "trust"),
    "on_plan":         ("customer", "plan",    "single", "semantic",     "trust"),
    "has_router":      ("customer", "router",  "single", "semantic",     "trust"),
    "prefers_channel": ("customer", "channel", "single", "semantic",     "trust"),
    "has_ticket":      ("customer", "ticket",  "multi",  "semantic",     "trust"),
    "owns_device":     ("customer", "device",  "multi",  "semantic",     "trust"),
    "reported_issue":  ("customer", "issue",   "multi",  "semantic",     "trust"),
    "has_status":      ("ticket",   "status",  "single", "coordination", "latest"),
    "assigned_to":     ("ticket",   "agent",   "single", "coordination", "latest"),
    "ticket_about":    ("ticket",   "issue",   "multi",  "semantic",     "trust"),
    "tried_fix":       ("ticket",   "fix",     "multi",  "episodic",     "trust"),
    "resolves":        ("fix",      "issue",   "multi",  "procedural",   "trust"),
    "affects":         ("outage",   "city",    "multi",  "semantic",     "trust"),
    # what a prospect or customer is planning or wants: kept apart from what is true now
    "moving_to":        ("customer", "city",     "single", "semantic", "trust"),
    "interested_in":    ("customer", "plan",     "multi",  "semantic", "trust"),
    "budget":           ("customer", "amount",   "single", "semantic", "trust"),
    "household_size":   ("customer", "count",    "single", "semantic", "trust"),
    "wants_to_buy":     ("customer", "plan",     "single", "semantic", "trust"),  # becomes an Order, never on_plan
    "current_provider": ("customer", "provider", "single", "semantic", "trust"),
    # who they are and what they came for, including every question they ask (episodic: the visit itself)
    "occupation":       ("customer", "occupation", "single", "semantic", "trust"),
    "address":          ("customer", "address",    "single", "semantic", "trust"),  # street address, for installs
    # what intake asked for and hasn't been told yet ("area", "plan", "router"); retired once the answer lands
    "awaiting":         ("customer", "info",       "multi",  "coordination", "latest"),
    "visit_reason":     ("customer", "reason",     "multi",  "episodic", "trust"),
    "asked_about":      ("customer", "topic",      "multi",  "episodic", "trust"),
    "requested":        ("customer", "request",    "multi",  "episodic", "trust"),
    # what they play and watch: sales and gaming/streaming support use it later
    "plays_game":       ("customer", "game",       "multi",  "semantic", "trust"),
    "watches":          ("customer", "title",      "multi",  "semantic", "trust"),
    # identity (intake spec 2a): asked once, kept forever. A phone/email/account is its own node, so two customers
    # sharing one is a graph match, not a string search.
    "phone":            ("customer", "phone",      "single", "semantic", "trust"),
    "email":            ("customer", "email",      "single", "semantic", "trust"),
    "account_id":       ("customer", "account",    "single", "semantic", "trust"),
    "alt_phone":        ("customer", "phone",      "single", "semantic", "trust"),
    "installed_at":     ("customer", "date",       "single", "semantic", "trust"),
    "connection_type":  ("customer", "connection", "single", "semantic", "trust"),  # home / business
    "preferred_name":   ("customer", "name",       "single", "semantic", "trust"),
    "preferred_language": ("customer", "language", "single", "semantic", "trust"),
    "billing_contact":  ("customer", "contact",    "single", "semantic", "trust"),
    # life events (spec 2d)
    "has_addon":        ("customer", "addon",      "multi",  "semantic", "trust"),
    "referred":         ("customer", "person",     "multi",  "episodic", "trust"),
    "previous_contact": ("customer", "when",       "multi",  "episodic", "trust"),  # "I called last week too"
    "service_request":  ("customer", "request_type", "multi", "episodic", "trust"),  # pause, cancel, relocate...
    "calling_for":      ("customer", "person",     "single", "episodic", "trust"),  # "my mother's connection"
    "on_waitlist":      ("customer", "city",       "multi",  "semantic", "trust"),  # (Lead)-[:ON_WAITLIST]->(place)
    "doesnt_know":      ("customer", "info",       "multi",  "coordination", "latest"),  # asked, they couldn't say
    # issue details on the ticket (spec 2c), so the resolver never has to ask
    "issue_type":       ("ticket",   "ticket_type", "single", "semantic", "trust"),
    "issue_started":    ("ticket",   "when",       "single", "semantic", "trust"),
    "frequency":        ("ticket",   "frequency",  "single", "semantic", "trust"),
    "severity":         ("ticket",   "severity",   "single", "semantic", "trust"),  # whole_home / single_device
    "affected_device":  ("ticket",   "device",     "multi",  "semantic", "trust"),
    "error_message":    ("ticket",   "text",       "single", "semantic", "trust"),
    "router_lights":    ("ticket",   "lights",     "single", "semantic", "trust"),
    "speed_reported":   ("ticket",   "speed",      "single", "semantic", "trust"),
    "connection_medium": ("ticket",  "medium",     "single", "semantic", "trust"),  # wifi / wired / both
    "affected_users":   ("ticket",   "count",      "single", "semantic", "trust"),
    "distance_from_router": ("ticket", "distance", "single", "semantic", "trust"),
    "has_priority":     ("ticket",   "priority",   "single", "coordination", "latest"),
}

# Ticket types (intake spec, issue trees). Extraction picks one for issue_type / service_request.
TICKET_TYPES = [
    "outage", "line_fault", "hardware_power", "device_or_line_fault", "speed_degradation", "congestion",
    "wifi_signal_weak", "wifi_drops", "connectivity_auth", "connectivity_capacity", "streaming_lag",
    "billing_dispute", "invoice_resend", "payment_reconciliation", "payment_method_change", "billing_query",
    "gst_invoice_request", "billing_date_change", "new_installation", "plan_upgrade", "plan_downgrade",
    "addon_add", "addon_removal", "service_pause", "relocation_same_city", "relocation_intercity",
    "cancellation_request", "router_config", "router_rebooting", "app_bug", "contact_update", "account_access",
]

LIFE = {
    "lives_in":          ("customer", "city",         "single", "semantic", "trust"),
    "works_at":          ("customer", "organization", "single", "semantic", "trust"),
    "job_title":         ("customer", "job",          "single", "semantic", "trust"),
    "studies":           ("customer", "subject",      "single", "semantic", "trust"),
    "relationship_with": ("customer", "person",       "multi",  "semantic", "trust"),
    "has_child":         ("customer", "person",       "multi",  "semantic", "trust"),
    "has_pet":           ("customer", "pet",          "multi",  "semantic", "trust"),
    "hobby":             ("customer", "activity",     "multi",  "semantic", "trust"),
    "owns":              ("customer", "thing",        "multi",  "semantic", "trust"),
    "likes":             ("customer", "thing",        "multi",  "semantic", "trust"),
    "dislikes":          ("customer", "thing",        "multi",  "semantic", "trust"),
    "visited":           ("customer", "place",        "multi",  "episodic", "trust"),
    "attended":          ("customer", "event",        "multi",  "episodic", "trust"),
    "plans_to":          ("customer", "plan",         "multi",  "semantic", "trust"),
    "identifies_as":     ("customer", "identity",     "single", "semantic", "trust"),
}

REGISTRIES = {"isp": ISP, "life": LIFE}
_ALL = {**LIFE, **ISP}  # shared names (lives_in) have identical definitions
PREDICATES = _ALL  # every known predicate; extraction uses the tenant's own registry


def for_tenant(tenant):
    # ponytail: name-prefix convention, no stored config; move to a tenant meta node if tenants need to switch.
    return "life" if str(tenant).startswith("life-") else "isp"


STATUSES = {"open", "in progress", "waiting on customer", "resolved"}
STATUS_ALIASES = {"fixed": "resolved", "closed": "resolved", "done": "resolved",
                  "working": "in progress", "pending": "waiting on customer", "waiting customer": "waiting on customer"}

# Free-text entity types that get embedding-based alias resolution ("wifi dropping" == "evening wifi drops").
# Not devices: product names are canonical and near-identical in embedding space (iphone/ipad = 0.174).
ALIAS_TYPES = {"issue", "fix", "outage", "topic", "reason", "request"}


# Open facts: anything concrete outside the registry ("works from home", "has two kids", "streams on Twitch") is kept
# as `open:<attribute>`, one current value per attribute. Attribute names are normalised by embedding similarity at
# write time (memory.open_predicate), so "works_remotely" and "works_from_home" become one attribute.
OPEN = ("customer", "value", "single", "semantic", "trust")


def is_open(p):
    return str(p).startswith("open:")


def open_name(attribute):
    slug = re.sub(r"[^a-z0-9]+", "_", str(attribute).lower()).strip("_")[:40]
    return f"open:{slug}" if slug else None


def _def(p):
    return OPEN if is_open(p) else _ALL[p]


def subject_type(p):
    return _def(p)[0]


def object_type(p):
    return _def(p)[1]


def is_single(p):
    return _def(p)[2] == "single"


def policy(p):
    return _def(p)[4]


def attribute(p):
    return p[5:].replace("_", " ") if is_open(p) else p.replace("_", " ")


# Graph naming, so FalkorDB Browser reads like the domain: (:Entity:Customer)-[:LIVES_IN]->(:Entity:City).
# Every entity keeps the shared :Entity label (indexes, vector search); the type label is added on top.
_LABEL_OVERRIDES = {"agent": "Assignee"}  # :Agent is taken by the agent nodes themselves


def label(entity_type):
    lab = _LABEL_OVERRIDES.get(entity_type) or "".join(w.capitalize() for w in str(entity_type).split("_"))
    if not lab.isalnum():
        raise ValueError(f"bad entity type {entity_type!r}")
    return lab


def rel_type(predicate):
    if is_open(predicate):
        t = predicate[5:].upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", t) or t in REL_TYPES_CORE:
            t = "HAS_" + t if re.fullmatch(r"[A-Z0-9_]{1,40}", t) else "HAS_ATTRIBUTE"
        return t
    if predicate not in _ALL:
        raise ValueError(f"unknown predicate {predicate!r}")
    return predicate.upper()


REL_TYPES_CORE = {p.upper() for p in _ALL}
REL_TYPES = sorted(rel_type(p) for p in _ALL)
REL_PATTERN = "|".join(REL_TYPES)  # e.g. -[:LIVES_IN|ON_PLAN|...*1..2]-: current-world fact edges only


def describe(registry="isp"):
    return "\n".join(f"- {p}: {s} -> {o} ({c}-valued)" for p, (s, o, c, _, _) in REGISTRIES[registry].items())
