"""Run: python test_app.py  (no pytest needed; LM Studio is simulated).

Mocks requests.post so no real model server is required.
"""
from unittest.mock import patch

import requests

from llm import (contains_fare_question, interpret, phrase_itinerary,
                 phrasing_is_faithful)
from router import Router, describe_itinerary, load_data

R = Router(load_data("routes.json"))


class FakeResp:
    def __init__(self, content, status=200):
        self.status_code = status
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    assert cond, label


GOOD_JSON = ('{"origin": "Cubao", "destination": "Divisoria", '
             '"preference": "fewest_transfers", "avoid": [], "follow_up": false}')

# 1. happy path: schema response parses and validates
with patch("llm.requests.post", return_value=FakeResp(GOOD_JSON)):
    out = interpret("paano pumunta galing cubao hanggang divisoria, kaunting lipat", R)
check("interpret ok", out["status"] == "ok")
check("origin/destination resolved",
      out["result"]["origin"] == "Cubao" and out["result"]["destination"] == "Divisoria")
check("preference kept", out["result"]["preference"] == "fewest_transfers")
check("raw output preserved", out["raw"] == GOOD_JSON)

# 2. retry: garbage first, good JSON second
calls = {"n": 0}


def flaky(url, json=None, timeout=None):
    calls["n"] += 1
    return FakeResp("hindi ko alam eh" if calls["n"] == 1 else GOOD_JSON)


with patch("llm.requests.post", side_effect=flaky):
    out = interpret("cubao to divisoria", R)
check("retry recovers", out["status"] == "ok_retry" and out["result"] is not None)

# 3. model down -> fallback
def down(url, json=None, timeout=None):
    raise requests.exceptions.ConnectionError("no server")


with patch("llm.requests.post", side_effect=down):
    out = interpret("cubao to divisoria", R)
check("connection error -> fallback",
      out["status"] == "fallback" and out["result"] is None)

# 4. slow model -> fallback


def slow(url, json=None, timeout=None):
    raise requests.exceptions.ConnectTimeout("too slow")


with patch("llm.requests.post", side_effect=slow):
    out = interpret("cubao to divisoria", R, timeout=1)
check("timeout -> fallback", out["status"] == "fallback")

# 5. avoid terms must appear in the user's text
AVOID_JSON = ('{"origin": null, "destination": null, "preference": null, '
              '"avoid": ["MRT", "teleport"], "follow_up": true}')
with patch("llm.requests.post", return_value=FakeResp(AVOID_JSON)):
    out = interpret("paano kung walang MRT?", R)
check("avoid filtered to words in text",
      out["result"]["avoid"] == ["MRT"] and out["result"]["follow_up"] is True)

# 6. unknown place -> dropped -> fallback
WEIRD_JSON = ('{"origin": "Mars", "destination": null, "preference": null, '
              '"avoid": [], "follow_up": false}')
with patch("llm.requests.post", return_value=FakeResp(WEIRD_JSON)):
    out = interpret("paano pumunta galing Mars?", R)
check("unknown place -> fallback", out["status"] == "fallback")

# 7. typo tolerance flows through the interpreter
TYPO_JSON = ('{"origin": "Divisoriaa", "destination": "Cubao", "preference": null, '
             '"avoid": [], "follow_up": false}')
with patch("llm.requests.post", return_value=FakeResp(TYPO_JSON)):
    out = interpret("divisoriaa to cubao", R)
check("typo tolerated in interpret", out["result"]["origin"] == "Divisoria")

# 8. bad preference value -> dropped, rest kept
PREF_JSON = ('{"origin": "Cubao", "destination": "Divisoria", "preference": "teleport", '
             '"avoid": [], "follow_up": false}')
with patch("llm.requests.post", return_value=FakeResp(PREF_JSON)):
    out = interpret("cubao to divisoria", R)
check("bad preference dropped", out["result"]["preference"] is None)

# 9. end-to-end pipeline: interpret -> plan with avoid -> describe (no peso)
with patch("llm.requests.post", return_value=FakeResp(GOOD_JSON)):
    out = interpret("cubao to divisoria", R)
res = out["result"]
opts = R.plan(res["origin"], res["destination"], avoid=res["avoid"])
txt = describe_itinerary(res["origin"], res["destination"], opts[0])
check("pipeline produces options", len(opts) > 0)
check("no peso in pipeline output", "₱" not in txt and "peso" not in txt.lower())

# 10. fare questions detected
check("fare question detected",
      contains_fare_question("magkano pamasahe cubao to divisoria?"))
check("non-fare not flagged",
      not contains_fare_question("paano pumunta galing cubao?"))

# 11. phrasing faithfulness: route names + transfer count, never fares
it = R.find_path("Cubao", "Divisoria", "fastest")
check("faithful simple",
      phrasing_is_faithful("Sakay Cubao - Divisoria Jeep mula Cubao hanggang Divisoria.", it))
check("unfaithful missing route",
      not phrasing_is_faithful("Masarap ang biyahe ngayon.", it))
it2 = R.find_path("Cubao", "Baclaran", "fastest")
names = " ".join(l["route"] for l in it2["legs"] if l["type"] != "Walk")
check("faithful with transfer word",
      phrasing_is_faithful(names + " may 1 lipat dito.", it2))
check("unfaithful without transfer word",
      not phrasing_is_faithful(names + " mabilis na biyahe.", it2))

# 12. phrase_itinerary returns text / None on failure
with patch("llm.requests.post", return_value=FakeResp("Ayos na biyahe!")):
    check("phrase returns text", phrase_itinerary("facts") == "Ayos na biyahe!")
with patch("llm.requests.post", return_value=FakeResp("x", status=500)):
    check("phrase None on http error", phrase_itinerary("facts") is None)

print("\nAll app tests passed.")
