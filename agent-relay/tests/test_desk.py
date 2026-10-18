"""Routing a customer to the desk that serves their address (api.main._other_desk), and place names ending a sentence.
No database, no LLM. Run: python -m tests.test_desk"""
from api.main import _other_desk
from relay import kb


def lives(o):
    return [{"triple": ("rupin", "lives_in", o)}]


def test_desk():
    # Chennai said on the Latin America desk: that desk has no network there, so the case moves to India
    d = _other_desk("pml-latam", lives("pattabiram"), "I'm in Pattabiram, Chennai.", "BR")
    assert d == {"tenant": "pml", "region": "India", "city": "Chennai", "country": "IN", "move": True}, d
    # Manchester while the Europe desk shows Germany: same graph, only the country (and its prices) changes
    d = _other_desk("pml-eu", lives("manchester"), "", "DE")
    assert d and d["tenant"] == "pml-eu" and d["country"] == "GB" and d["move"] is False, d
    # already matching, or not a place we serve: nothing to do
    assert _other_desk("pml", lives("chennai"), "", "IN") is None
    assert _other_desk("pml-eu", lives("manchester"), "", "GB") is None
    assert _other_desk("pml", lives("goa"), "", "IN") is None  # Goa, India on the India desk: no move
    assert _other_desk("pml", [{"triple": ("rupin", "phone", "9876543210")}], "", "IN") is None


def test_place_at_sentence_end():
    assert kb.resolve_place("I'm in Pattabiram, Chennai.")["key"] == "chennai"   # the full stop doesn't hide the city
    assert kb.resolve_place("Im in T. Nagar, Chennai.")["key"] == "t. nagar"    # a dot inside a name still matches
    assert kb.resolve_place("moved to Pune!")["key"] == "pune"
    assert kb.resolve_place("pattabiram") is None                               # a suburb we don't list


def test_geo_without_network():
    """The resolver's offline layers (no OpenCage key in tests, so it never calls out): our catalogue, the GeoNames town
    list, and nearest-served-city maths."""
    from relay import geo
    assert geo.place("near Avadi railway station", "in")["key"] == "avadi"      # catalogue, anywhere in the text
    p = geo.place("Tambaram", "in")
    assert p["city"] == "chennai" and p["served"]
    n = geo.nearest(13.1166, 80.1037, "IN")                                    # Pattabiram's position
    assert n["city"] == "chennai" and n["area"] == "avadi" and n["served"] and n["km"] < 40, n
    far = geo.nearest(35.0, 75.0, "IN")                                        # high in the Himalaya
    assert not far["served"]
    if not geo.KEY:
        assert geo.place("navajeevan nagar xyz", "in") is None                 # unknown and no geocoder: nothing


if __name__ == "__main__":
    test_desk()
    test_place_at_sentence_end()
    test_geo_without_network()
    print("desk routing ok")
