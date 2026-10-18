"""An issue alias never hands one customer another's detail: "slow internet" must not become someone else's "wifi slow
upstairs". No database, no LLM. Run: python -m tests.test_alias_qualifiers"""
from relay.memory import _qualifiers


def same(a, b):
    return _qualifiers(a) == _qualifiers(b)


def test_qualifiers():
    assert not same("slow internet", "wifi slow upstairs")
    assert not same("slow wifi in bedroom", "slow wifi in kitchen")
    assert not same("speed drops", "speed drops at night")
    # paraphrases that name the same where/when/what still merge
    assert same("no internet", "internet not working")
    assert same("router keeps rebooting", "router restarts by itself")
    assert same("tv cannot connect", "smart tv cannot connect")
    assert same("calls drop", "video calls freeze")
    assert _qualifiers("printer offline") == {"printer"} and _qualifiers("upstairs bedroom") == {"upstairs", "bedroom"}


if __name__ == "__main__":
    test_qualifiers()
    print("ok")
