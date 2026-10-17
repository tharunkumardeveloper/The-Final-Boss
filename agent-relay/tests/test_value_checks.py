"""Write-time value checks (registry.valid_value): values no fact of that type can hold are dropped before the write.
No database, no LLM. Run: python -m tests.test_value_checks"""
from relay import registry as R


def test_value_checks():
    # the benchmark's last miss: a router recorded as "wifi"
    for bad in ("wifi", "Wi-Fi", "router", "the router", "modem", "internet", ""):
        assert not R.valid_value("has_router", bad), bad
    for good in ("pml hub 6 pro", "tp-link archer c6", "jio fiber router x1"):
        assert R.valid_value("has_router", good), good
    # places: a city is a place, not "home"
    assert not R.valid_value("lives_in", "home") and not R.valid_value("moving_to", "here")
    assert R.valid_value("lives_in", "pune") and R.valid_value("lives_in", "t. nagar")
    # identity: a phone has digits, an email has a domain
    assert R.valid_value("phone", "9254695216") and R.valid_value("alt_phone", "+91 98765 43210")
    assert not R.valid_value("phone", "my number") and not R.valid_value("phone", "12345")
    assert R.valid_value("email", "asha.menon@example.com")
    assert not R.valid_value("email", "asha at gmail") and not R.valid_value("email", "asha@gmail")
    # types without a rule are untouched
    assert R.valid_value("reported_issue", "wifi") and R.valid_value("connection_medium", "wifi")
    assert R.valid_value("open:works_from_home", "yes") and R.valid_value("household_size", "four")


if __name__ == "__main__":
    test_value_checks()
    print("value checks ok")
