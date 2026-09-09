"""The set of verticals this project actually has stored frameworks for."""

from frameworks.vertical import KNOWN_VERTICALS


def test_known_verticals_matches_the_six_real_frameworks():
    assert KNOWN_VERTICALS == {
        "saas",
        "plg",
        "marketplace",
        "ecommerce",
        "services-project",
        "transactional",
    }
