"""Feed outages end: the resolver retires what the feed no longer reports, so the portal banner can't go stale
(found in the browser pass: "Fiber cut near Baner" showed forever). Run: python -m tests.test_outage_feed"""
from relay import agents, db, memory, retrieve, sim, tools

T = "test-outage-feed"
DAY = 24 * sim.HOUR


def live(outage):
    return {o for _, p, o, on, *_ in retrieve.history(T, outage) if on and p == "affects"}


def main():
    db.reset(T)
    tools.WORLDS[T] = sim.WORLD
    assert tools.outages_in("pune", T, sim.START + 4 * DAY) == ["fiber cut near baner"]
    assert tools.outages_in("pune", T, sim.START + 6 * DAY) == []
    assert tools.outages_in("pune", T) == ["fiber cut near baner"], "no time given: the whole feed"
    memory.remember(T, agent="resolver", session_id="work-x", customer=None, at=sim.START + 4 * DAY, speaker="tool:outage",
                    text="Outage feed: fiber cut near baner affects pune", facts=[("fiber cut near baner", "affects", "pune")])
    memory.remember(T, agent="noc", session_id="noc-x", customer=None, at=sim.START + 4 * DAY, speaker="noc",
                    text="NOC: olt down", facts=[("olt-pune-baner down", "affects", "baner")])
    assert not agents.sweep_outages(T, sim.START + 4 * DAY), "still reported on day 4"
    assert live("fiber cut near baner") == {"pune"}
    gone = agents.sweep_outages(T, sim.START + 6 * DAY)
    assert gone and not live("fiber cut near baner"), "retired once the feed stops reporting it"
    assert live("olt-pune-baner down") == {"baner"}, "NOC outages are the NOC's to end"
    del tools.WORLDS[T]
    db.graph(T).delete()


if __name__ == "__main__":
    main()
    print("test_outage_feed: all checks passed")
