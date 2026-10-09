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

## Hackathon submission (App Builders PH 2026 -- Local AI)

**Short description:** A Taglish commute assistant for Metro Manila that runs
on the user's own device. A local LLM understands free-form questions; a
deterministic router picks the route; nothing needs the internet.

**Why does this product benefit from running AI locally?**
- **Works with no signal or data.** Commuters lose signal underground, in packed
  stations, and during floods/typhoons, and many ride without mobile data.
- **Private.** Where you go every day is sensitive; trip questions never leave
  the device.
- **Free and fast.** No per-query API cost or network round-trip; a 2B model
  runs on an ordinary laptop.
- **Safe.** The model only interprets and rephrases. Routes come from the
  deterministic router, a faithfulness check rejects rephrasings that change
  the route, and fares are never invented.

### What runs locally
| Component | Where it runs |
|---|---|
| Query understanding (Taglish -> origin/destination/preference/avoid JSON) | Gemma-2-2b via LM Studio on `localhost:1234` |
| Answer rephrasing + faithfulness check | Gemma-2-2b via LM Studio, checked in `llm.py` |
| Route search (Dijkstra over `routes.json`) | Python, `router.py` |
| Rules-based fallback parser | Python, `router.py` |
| Text-to-speech | Browser `speechSynthesis` (use an installed OS voice) |
| QR code generation | `qrcode` + Pillow |
| UI | Streamlit served on `localhost:8501` (usage stats disabled in `.streamlit/config.toml`) |

### What requires internet
- One-time setup only: `pip install`, downloading LM Studio and the model.
- Optional: the WhatsApp share button opens `wa.me`.
- Some browser voices (e.g. Chrome's "Google ..." voices) are cloud-backed;
  pick a local OS voice for fully offline speech.

### Disclosures
- **Models:** Gemma-2-2b (Google, open weights), run through LM Studio.
- **Technologies/frameworks:** Python, Streamlit, Requests, qrcode, Pillow,
  pytest, LM Studio (OpenAI-compatible local server).
- **APIs and cloud services:** none at runtime.
- **Data:** station lists for LRT-1, LRT-2, MRT-3 and EDSA Carousel compiled
  from public line information; jeepney/UV routes are an unverified starter set.
- **Existing code and assets:** _fill in what existed before Build Day, if anything._
- **AI development tools:** Devin (Cognition) -- debugging, router rewrite,
  station data, UI redesign, tests.

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
