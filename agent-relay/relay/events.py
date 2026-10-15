"""Per-tenant event bus. Engine code stays synchronous and calls emit(); the API bridges to WebSockets."""
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_subs: dict[str, list] = {}
_lock = threading.Lock()


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=IST).isoformat(timespec="seconds") if ms is not None else None


def subscribe(tenant, fn):
    """fn(event) is called from whatever thread emits. Returns an unsubscribe function."""
    with _lock:
        _subs.setdefault(tenant, []).append(fn)

    def unsubscribe():
        with _lock:
            if fn in _subs.get(tenant, []):
                _subs[tenant].remove(fn)
    return unsubscribe


def listening(tenant):
    return bool(_subs.get(tenant))


def emit(tenant, type_, data, at=None):
    """at: simulated time (epoch ms) of the event, if known."""
    with _lock:
        fns = list(_subs.get(tenant, ()))
    if not fns:
        return
    ev = {"id": uuid.uuid4().hex[:16], "type": type_, "sim_time": iso(at), "wall": int(time.time() * 1000), "data": data}
    for fn in fns:
        try:
            fn(ev)
        except Exception:  # a broken subscriber must never break a memory write
            pass


def emit_all(type_, data):
    """Broadcast to every tenant's listeners (global things like LLM usage)."""
    with _lock:
        tenants = list(_subs)
    for t in tenants:
        emit(t, type_, data)


if __name__ == "__main__":
    got = []
    off = subscribe("t", got.append)
    emit("t", "clock", {"sim_time": "x"}, at=0)
    emit("other", "clock", {})
    off()
    emit("t", "clock", {})
    assert len(got) == 1 and got[0]["sim_time"].startswith("1970-01-01T05:30"), got
    print("events ok")
