"""Tests for router.py. Run: python -m pytest test_router.py -q"""
import json

import pytest

from router import MODE_LABELS, PREFERENCES, Router, describe_itinerary, describe_plan, load_data


@pytest.fixture
def sample_routes():
    return [
        {"name": "MRT-3", "type": "Train",
         "stops": ["North Ave", "Quezon Ave", "Cubao", "Shaw Blvd", "Ayala", "Taft Avenue"],
         "details": "Main rapid transit line along EDSA."},
        {"name": "Ayala-Washington Jeep", "type": "Jeepney",
         "stops": ["MRT Ayala", "Chino Roces", "Washington Street", "Gil Puyat Ave"],
         "details": "Board near Ayala Ave."},
        {"name": "Cubao-Divisoria Jeep", "type": "Jeepney",
         "stops": ["Gateway Cubao", "Aurora Blvd", "Stop & Shop", "Legarda", "Recto", "Divisoria"],
         "details": "Aurora Blvd to Divisoria."},
        {"name": "Walk: Cubao - Gateway Cubao", "type": "Walk",
         "stops": ["Cubao", "Gateway Cubao"], "details": "Short walk."},
        {"name": "Walk: Ayala - MRT Ayala", "type": "Walk",
         "stops": ["Ayala", "MRT Ayala"], "details": "Short walk."},
    ]


@pytest.fixture
def router(sample_routes):
    return Router(sample_routes)


@pytest.fixture
def real_router():
    return Router(load_data("routes.json"))


# ---------------------------------------------------------------- data
def test_load_data(tmp_path, sample_routes):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(sample_routes))
    data = load_data(str(p))
    assert len(data) == len(sample_routes) and data[0]["name"] == "MRT-3"


def test_load_data_missing():
    assert load_data("nonexistent.json") == []


def test_nodes(router):
    assert {"North Ave", "Cubao", "Divisoria"} <= set(router.nodes)


def test_real_data_has_no_fares():
    for r in load_data("routes.json"):
        assert not any("fare" in k.lower() or "price" in k.lower() for k in r)


def test_mode_labels_cover_preferences():
    assert set(MODE_LABELS) == set(PREFERENCES)


# ---------------------------------------------------------------- places
@pytest.mark.parametrize("text,expected", [
    ("Cubao", "Cubao"), ("cubao", "Cubao"), ("North Avenue", "North Ave"),
    ("Divisoriaa", "Divisoria"), ("Washington", "Washington Street"),
])
def test_resolve_place(router, text, expected):
    assert router.resolve_place(text) == expected


@pytest.mark.parametrize("text", ["Mars", "", "how", "  "])
def test_resolve_place_unknown(router, text):
    assert router.resolve_place(text) is None


# ---------------------------------------------------------------- parser
def test_parse_galing_hanggang(router):
    q = router.parse_query("Paano pumunta galing Cubao hanggang Divisoria?")
    assert (q["origin"], q["dest"]) == ("Cubao", "Divisoria")


def test_parse_with_to(router):
    q = router.parse_query("How to get from Ayala to Shaw?")
    assert (q["origin"], q["dest"]) == ("Ayala", "Shaw Blvd")


def test_parse_incomplete(router):
    q = router.parse_query("Paano pumunta?")
    assert q["origin"] is None and q["dest"] is None


@pytest.mark.parametrize("word", ["diretso", "direktso", "direct"])
def test_parse_preference(router, word):
    q = router.parse_query(f"Paano pumunta galing Cubao hanggang Divisoria na {word}?")
    assert q["preference"] == "fewest_transfers"
    assert q["dest"] == "Divisoria"


def test_parse_avoid(router):
    q = router.parse_query("Paano pumunta galing Cubao hanggang Divisoria iwas jeep?")
    assert q["avoid"] == ["jeep"]


def test_avoid_is_not_a_line_query(router):
    q = router.parse_query("paano kung walang jeep?")
    assert q["avoid"] == ["jeep"] and q["line"] is None


def test_parse_line(router):
    assert router.parse_query("Anong mga hinto ng MRT-3?")["line"] == "MRT-3"


# ---------------------------------------------------------------- routing
def test_plan_basic(router):
    opts = router.plan("Cubao", "Divisoria")
    assert opts and opts[0]["legs"]
    assert opts[0]["legs"][0]["type"] == "Walk"
    assert opts[0]["transfers"] == 0


def test_plan_with_transfer(router):
    opts = router.plan("North Ave", "Divisoria")
    best = opts[0]
    assert [l["route"] for l in best["legs"] if l["type"] != "Walk"] == \
        ["MRT-3", "Cubao-Divisoria Jeep"]
    assert best["transfers"] == 1
    assert best["legs"][0]["to"] == "Cubao"


def test_option_shape(router):
    opt = router.plan("North Ave", "Washington")[0]
    for k in ("legs", "mins", "stops", "transfers", "modes", "origin", "destination"):
        assert k in opt
    for leg in opt["legs"]:
        for k in ("type", "route", "stops", "hops", "mins", "details", "to"):
            assert k in leg
    assert "fare" not in opt


def test_every_preference_is_assigned(router):
    opts = router.plan("North Ave", "Divisoria")
    assert sorted(m for o in opts for m in o["modes"]) == sorted(PREFERENCES)


def test_preference_moves_option_first(real_router):
    opts = real_router.plan("Cubao", "Divisoria", preference="fewest_stops")
    assert "fewest_stops" in opts[0]["modes"]


def test_avoid(router):
    assert router.plan("North Ave", "Divisoria", avoid=["jeep"]) == []
    assert router.plan("North Ave", "Ayala", avoid=["MRT"]) == []
    assert router.plan("North Ave", "Ayala", avoid=["jeep"])


def test_parallel_routes_kept(real_router):
    # Carousel North and South share edges; the graph must keep both
    routes = {r["name"] for _, r in real_router.adj["Shaw Blvd"]}
    assert {"EDSA Carousel North", "EDSA Carousel South"} <= routes


@pytest.mark.parametrize("a,b", [("Cubao", "Cubao"), ("Mars", "Divisoria"), ("Cubao", "Mars")])
def test_plan_invalid(router, a, b):
    assert router.plan(a, b) == []


@pytest.mark.parametrize("a,b", [("Cubao", "Divisoria"), ("Ayala", "Washington"),
                                 ("North Avenue", "Antipolo"), ("Cubao", "Baclaran")])
def test_quick_buttons_have_routes(real_router, a, b):
    assert real_router.plan(a, b)


# ---------------------------------------------------------------- lines
def test_line_info(router):
    assert router.line_info("MRT-3")["name"] == "MRT-3"
    assert router.line_info("Ayala-Washington")["type"] == "Jeepney"
    assert router.line_info("NonExistent Line") is None
    assert router.line_info("Walk") is None


# ---------------------------------------------------------------- text
def test_describe_itinerary(router):
    opt = router.plan("North Ave", "Divisoria")[0]
    txt = describe_itinerary("North Ave", "Divisoria", opt)
    assert "North Ave" in txt and "Divisoria" in txt and "MRT-3" in txt and "lipat" in txt.lower()
    assert "₱" not in txt and "peso" not in txt.lower()


def test_describe_plan(router):
    txt = describe_plan("North Ave", "Divisoria", router.plan("North Ave", "Divisoria"))
    assert "Opsyon 1" in txt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
