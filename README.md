# 📍 Paano Pumunta AI

Offline commute helper for Metro Manila. Type a trip in Taglish and get routes
with transfers and rough time estimates.

**No fares -- by design.** Fares change often and are frequently wrong, so this
app never stores, computes, shows, or invents peso amounts. If you ask about
fares, it tells you to ask the driver or check the operator.

## How it works

1. **Local AI interpreter** (`llm.py`) turns messy Taglish into structured trip
   details -- origin, destination, preference, things to avoid -- using a local
   model (Gemma-2-2b) served by LM Studio. Single user message, no system role,
   JSON schema with one retry. Every field is validated against the route graph.
   It never chooses routes.
2. **Rules-based parser** (`router.py`) fills in whatever the model missed, and
   takes over fully if the model is down or slow (20s timeout).
3. **Deterministic router** (Dijkstra over a stop graph from `routes.json`) is
   the ONLY thing that chooses routes: fastest, fewest stops, fewest transfers.
4. **Local AI phrasing** (optional) rephrases the chosen itinerary in friendly
   Taglish. A faithfulness check (route names + transfer count) discards it if
   the model invents anything; the deterministic template is used instead.

## Coverage

| Line | Stations | Status |
|---|---|---|
| LRT-1 | 25 (Fernando Poe Jr. to Dr. Santos, incl. Cavite Extension Phase 1) | verified station order |
| LRT-2 | 13 (Recto to Antipolo) | verified station order |
| MRT-3 | 13 (North Avenue to Taft Avenue) | verified station order |
| EDSA Carousel | 21 (Monumento to PITX) | stop list may change |
| Jeepney / UV Express | starter set | **unverified** -- used only when no verified route exists, flagged in the UI |

Rail transfers are modelled as walk links: Doroteo Jose-Recto, EDSA-Taft Avenue,
and the shared Araneta Center-Cubao node (LRT-2/MRT-3). Common names like
"Cubao", "MOA", "NAIA", "Shaw", "UP" resolve to the right station.

## What runs locally

Everything: parsing, routing, the LLM (LM Studio on localhost), and
text-to-speech (the browser's built-in speech synthesis). Nothing requires
internet. No external images, fonts, or CDNs.

## Run

```
pip install -r requirements.txt
python -m streamlit run app.py
```

Optional: start LM Studio's local server (default port 1234) with Gemma-2-2b
loaded for the AI features. Without it, the app still works with rules-based
parsing and template answers.

## Test

```
python -m pytest test_router.py -q
python test_app.py    # simulated LM Studio -- no server needed
```

## Add routes

Append to `routes.json` and reuse existing stop names so transfers connect.
Set `"verified": false` for routes you have not confirmed. Link nearby stops with
`{"name": "Walk: A - B", "type": "Walk", "stops": ["A", "B"]}`. Never add fare fields.

## Limitations (be upfront in the demo)

- Rail station order is real; jeepney and UV routes are a small unverified
  starter set and need checking before real-world use.
- Times are rough estimates, not schedules. No live traffic.
- No fare information, by design.
- Routes are treated as two-way in the graph (one-way jeep loops are not modelled).
