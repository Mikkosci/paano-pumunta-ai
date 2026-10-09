"""Paano Pumunta AI -- offline commute guide for Metro Manila.

Fully offline: routing, parsing, the local LLM (LM Studio) and text-to-speech
all run on this device. No fares are shown anywhere -- by design.
"""
import html
import json
import re
import time
import urllib.parse
from io import BytesIO

import qrcode
import streamlit as st
import streamlit.components.v1 as components

import router as _router_module
from llm import (DEFAULT_MODEL, DEFAULT_URL, FARE_DISCLAIMER,
                 contains_fare_question, interpret, phrase_itinerary,
                 phrasing_is_faithful)
from router import Router, describe_itinerary, load_data

MODE_LABELS = getattr(_router_module, "MODE_LABELS", {})

st.set_page_config(page_title="Paano Pumunta AI", page_icon="📍", layout="wide")

LINE_COLORS = {"LRT-1": "#2e7d32", "LRT-2": "#7b1fa2", "MRT-3": "#f9a825", "EDSA Carousel": "#1565c0"}
TYPE_COLORS = {"Train": "#455a64", "Bus": "#1565c0", "Jeepney": "#ef6c00", "UV Express": "#00838f",
               "Walk": "#9e9e9e"}
TYPE_ICON = {"Train": "🚆", "Bus": "🚌", "Jeepney": "🚙", "UV Express": "🚐", "Walk": "🚶"}


def route_color(name, rtype):
    return LINE_COLORS.get(name, TYPE_COLORS.get(rtype, "#607d8b"))


# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.block-container { padding-top: 1.5rem; max-width: 1100px; }
.hero { background: linear-gradient(135deg, #0d47a1 0%, #1976d2 55%, #26a69a 100%);
  padding: 22px 26px; border-radius: 18px; color: white; margin-bottom: 14px; }
.hero h1 { color: white !important; font-size: 34px !important; margin: 0 !important; padding: 0 !important; }
.hero p { color: rgba(255,255,255,.9); margin: 4px 0 10px 0; font-size: 16px; }
.pill { display: inline-block; background: rgba(255,255,255,.18); color: white; padding: 4px 12px;
  border-radius: 999px; font-size: 12px; font-weight: 600; margin: 2px 6px 2px 0; }
.card { background: #ffffff; color: #1f2937; border-radius: 14px; padding: 14px 16px; margin: 10px 0;
  box-shadow: 0 1px 3px rgba(0,0,0,.08), 0 4px 14px rgba(0,0,0,.05); border-left: 6px solid #1976d2; }
.card h4 { margin: 0 0 4px 0 !important; padding: 0 !important; font-size: 16px !important; color: #111827 !important; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;
  color: white; margin-right: 6px; }
.warn { background: #fff4e5; color: #8a4b00; border: 1px solid #ffb74d; }
.muted { color: #6b7280; font-size: 13px; }
.stops { color: #374151; margin: 6px 0 2px 0; font-size: 14px; line-height: 1.6; }
.xfer { color: #92400e; background: #fffbeb; border: 1px dashed #f59e0b; border-radius: 10px;
  padding: 6px 12px; margin: 4px 0 4px 18px; font-size: 13px; }
.summary { display: flex; gap: 10px; flex-wrap: wrap; margin: 6px 0 4px 0; }
.stat { background: #eef2ff; color: #1e3a8a; border-radius: 10px; padding: 6px 12px; font-weight: 700; font-size: 14px; }
.opt-head { font-weight: 800; font-size: 17px; margin: 18px 0 4px 0; }
.timeline { border-left: 4px solid var(--c); margin: 8px 0 8px 10px; padding-left: 18px; }
.station { position: relative; padding: 5px 0; color: inherit; }
.station:before { content: ""; position: absolute; left: -27px; top: 9px; width: 14px; height: 14px;
  border-radius: 50%; background: white; border: 4px solid var(--c); }
.xtag { font-size: 11px; background: #f3f4f6; color: #374151; border-radius: 6px; padding: 1px 6px; margin-left: 6px; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <h1>📍 Paano pumunta?</h1>
  <p>Metro Manila commute guide -- type your trip in Taglish or pick stations below.</p>
  <span class="pill">📴 Works offline</span><span class="pill">🤖 Local AI</span>
  <span class="pill">🚆 LRT-1 · LRT-2 · MRT-3 · EDSA Carousel</span><span class="pill">🚫 No fares, by design</span>
</div>
""", unsafe_allow_html=True)


@st.cache_resource
def get_router():
    return Router(load_data("routes.json"))


router = get_router()

_REQUIRED = ("resolve_place", "find_path", "plan", "parse_query", "line_info")
_probe = router.plan(router.nodes[0], router.nodes[-1]) if len(router.nodes) > 1 else []
if (not all(hasattr(router, a) for a in _REQUIRED)
        or any("stops" not in o or "modes" not in o for o in _probe)):
    st.cache_resource.clear()
    st.error("Outdated router.py loaded from: " + _router_module.__file__ + "\n\n"
             "Replace it with the router.py that matches this app.py, delete the "
             "__pycache__ folder, then stop Streamlit (Ctrl+C) and run it again.")
    st.stop()

RIDE_ROUTES = [r for r in router.routes if r["type"] != "Walk"]
STATIONS = sorted(router.nodes)

# ---------------------------------------------------------------- state
ss = st.session_state
ss.setdefault("messages", [])
ss.setdefault("request_count", 0)
ss.setdefault("latency", None)
ss.setdefault("ai_mode", "—")
ss.setdefault("recent_searches", [])
ss.setdefault("last_trip", None)


def queue(p, forced=None):
    ss["queued"] = p
    ss["queued_forced"] = forced
    if p not in ss["recent_searches"]:
        ss["recent_searches"] = (ss["recent_searches"] + [p])[-10:]


def get_difficulty(opt):
    t = opt["transfers"]
    if t == 0:
        return "Diretso", "#2e7d32"
    if t == 1:
        return "1 lipat", "#ef6c00"
    return f"{t} lipat", "#c62828"


def speak(text):
    """Read text aloud via the browser's built-in (on-device) speech synthesis."""
    cleaned = re.sub(r"[*_`#]", "", text)
    components.html(
        "<script>var u=new SpeechSynthesisUtterance(" + json.dumps(cleaned).replace("<", "\\u003c") + ");"
        "u.lang='fil-PH';speechSynthesis.cancel();speechSynthesis.speak(u);</script>",
        height=0)


def qr_image(text):
    try:
        buf = BytesIO()
        qrcode.make(text).save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


def transfer_lines(stop, exclude):
    """Other ride lines reachable at a stop (directly or via a walk link)."""
    names = set()
    for nxt, r in router.adj.get(stop, []):
        if r["type"] == "Walk":
            names |= {r2["name"] for _, r2 in router.adj.get(nxt, []) if r2["type"] != "Walk"}
        else:
            names.add(r["name"])
    names.discard(exclude)
    return sorted(names)


# ---------------------------------------------------------------- render
def render_itinerary(opt):
    labels = " · ".join(MODE_LABELS.get(m, m) for m in opt["modes"])
    diff, diff_color = get_difficulty(opt)
    st.markdown(
        f'<div class="opt-head">✅ {html.escape(labels)} '
        f'<span class="badge" style="background:{diff_color}">{diff}</span></div>'
        f'<div class="summary"><span class="stat">⏱️ ~{opt["mins"]} min</span>'
        f'<span class="stat">🚏 {opt["stops"]} hinto</span>'
        f'<span class="stat">🔄 {opt["transfers"]} lipat</span></div>',
        unsafe_allow_html=True)
    if opt.get("unverified"):
        st.markdown('<div class="card warn">⚠️ May bahagi ng rutang ito na <b>hindi pa beripikado</b> '
                    f'({html.escape(", ".join(opt["unverified"]))}). Kumpirmahin sa driver o sa terminal.</div>',
                    unsafe_allow_html=True)
    for i, leg in enumerate(opt["legs"]):
        color = route_color(leg["route"], leg["type"])
        icon = TYPE_ICON.get(leg["type"], "🚏")
        stops = [html.escape(s) for s in leg["stops"]]
        stops[0], stops[-1] = f"<b>{stops[0]}</b>", f"<b>{stops[-1]}</b>"
        title = "Maglakad" if leg["type"] == "Walk" else html.escape(leg["route"])
        flag = "" if leg.get("verified", True) else '<span class="badge warn">unverified</span>'
        st.markdown(f"""
        <div class="card" style="border-left-color:{color}">
          <h4>{icon} {title} <span class="badge" style="background:{color}">{html.escape(leg['type'])}</span>{flag}</h4>
          <div class="stops">{' → '.join(stops)}</div>
          <div class="muted">{leg['hops']} hinto · ~{leg['mins']} min · {html.escape(leg.get('details', ''))}</div>
        </div>""", unsafe_allow_html=True)
        if i < len(opt["legs"]) - 1 and leg["type"] != "Walk" and opt["legs"][i + 1]["type"] != "Walk":
            st.markdown(f'<div class="xfer">🔄 Lipat sa <b>{html.escape(leg["to"])}</b></div>',
                        unsafe_allow_html=True)


def render_line(route, compact=False):
    color = route_color(route["name"], route["type"])
    rows = []
    for s in route["stops"]:
        xs = transfer_lines(s, route["name"])
        tag = f'<span class="xtag">🔄 {html.escape(", ".join(xs))}</span>' if xs else ""
        rows.append(f'<div class="station">{html.escape(s)}{tag}</div>')
    flag = "" if route.get("verified", True) else '<span class="badge warn">unverified</span>'
    st.markdown(f"""
    <div class="card" style="border-left-color:{color}">
      <h4>{TYPE_ICON.get(route['type'], '🚏')} {html.escape(route['name'])}
        <span class="badge" style="background:{color}">{html.escape(route['type'])}</span>{flag}</h4>
      <div class="muted">{len(route['stops'])} hinto · {html.escape(route.get('details', ''))}</div>
    </div>""", unsafe_allow_html=True)
    if not compact:
        st.markdown(f'<div class="timeline" style="--c:{color}">{"".join(rows)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- answer
def answer(prompt, forced=None):
    """Return (text, payload, debug) for a user prompt.

    `forced` (from the station picker) skips interpretation entirely. Otherwise
    the local model interprets the message and the rules parser fills gaps.
    The deterministic router is the only thing that chooses routes.
    """
    interp, result = None, None
    if forced:
        result = {"origin": forced["origin"], "destination": forced["destination"],
                  "preference": forced.get("preference"), "avoid": forced.get("avoid", []),
                  "follow_up": False}
    elif use_llm:
        interp = interpret(prompt, router, llm_url, llm_model)
        result = interp.get("result")

    origin = result["origin"] if result else None
    dest = result["destination"] if result else None
    preference = (result.get("preference") if result else None) or "fastest"
    avoid = result["avoid"] if result else []

    if result and result["follow_up"] and ss.last_trip:
        origin = origin or ss.last_trip["origin"]
        dest = dest or ss.last_trip["destination"]

    q = {} if forced else (router.parse_query(prompt) or {})
    q_avoid = q.get("avoid") or []
    if isinstance(q_avoid, str):
        q_avoid = [q_avoid]
    q_pref = q.get("preference")
    if not origin or not dest:
        if q.get("line") and not (q.get("origin") and q.get("dest")) and not origin and not dest:
            r = router.line_info(q["line"])
            if r:
                return f"Ito ang mga hinto ng {r['name']}: {', '.join(r['stops'])}.", {"line": r}, interp
        origin = origin or q.get("origin")
        dest = dest or q.get("dest")
    if not result:
        preference = q_pref or preference
        avoid = q_avoid
        if not origin and not dest and (q_avoid or q_pref) and ss.last_trip:
            origin, dest = ss.last_trip["origin"], ss.last_trip["destination"]

    fare_q = contains_fare_question(prompt)

    if not origin and not dest:
        text = ("Hindi ko makita kung saan ka galing o pupunta. Subukan: "
                "'Paano pumunta galing Cubao hanggang Divisoria?' o gamitin ang station picker sa itaas.")
        return (FARE_DISCLAIMER + " " + text if fare_q else text), None, interp
    if not origin or not dest:
        known = origin or dest
        missing = "pupuntahan" if origin else "pinanggalingan"
        return (f"Nakita ko ang {known}, pero ano ang {missing}? "
                "Pakibigay ang buong biyahe (hal. 'Cubao to Divisoria')."), None, interp
    if origin == dest:
        return "Pareho ang pinanggalingan at pupuntahan. Nandiyan ka na! 😄", None, interp

    options = router.plan(origin, dest, avoid=avoid, preference=preference)
    if not options:
        extra = f" nang hindi sumasakay ng {', '.join(avoid)}" if avoid else ""
        return (f"Walang ruta sa database mula {origin} papuntang {dest}{extra}. "
                "Dagdagan ang routes.json para sa biyaheng ito."), None, interp

    best = next((o for o in options if preference in o["modes"]), options[0])
    facts = describe_itinerary(origin, dest, best)

    text, mode = facts, "Template (deterministic)"
    if use_llm:
        out = phrase_itinerary(facts, llm_url, llm_model)
        if out and phrasing_is_faithful(out, best):
            text, mode = out, "Local AI phrasing (LM Studio)"
        else:
            mode = "Template (AI unavailable or unverified)"
    if fare_q:
        text += "\n\n" + FARE_DISCLAIMER

    interp_status = "station picker" if forced else (interp["status"] if interp else "off")
    ss.ai_mode = f"Interpret: {interp_status} · {mode}"
    ss.last_trip = {"origin": origin, "destination": dest}
    payload = {"origin": origin, "destination": dest, "options": options,
               "best": best, "preference": preference, "facts": facts}
    return text, payload, interp


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    use_llm = st.toggle("Use local AI (LM Studio)", value=True)
    with st.expander("LM Studio connection"):
        llm_url = st.text_input("LM Studio URL", DEFAULT_URL)
        llm_model = st.text_input("Model name", DEFAULT_MODEL)
    st.caption("The model only interprets your message and rephrases answers. "
               "Routes are always chosen by the deterministic router.")
    st.divider()
    c1, c2 = st.columns(2)
    c1.metric("Lines", len(RIDE_ROUTES))
    c2.metric("Stops", len(router.nodes))
    c1.metric("Questions", ss.request_count)
    c2.metric("Last reply", f"{ss.latency:.1f}s" if ss.latency else "—")
    st.caption(f"Answer mode: {ss.ai_mode}")
    st.divider()
    if st.button("🔄 Reset conversation", width="stretch"):
        ss.messages, ss.request_count, ss.latency, ss.ai_mode = [], 0, None, "—"
        ss.recent_searches, ss.last_trip = [], None
        st.rerun()
    history_text = "\n\n".join(f"{m['role'].title()}: {m['content']}" for m in ss.messages)
    st.download_button("📥 Export chat", data=history_text, file_name="paano_pumunta_chat.txt",
                       mime="text/plain", width="stretch", disabled=not ss.messages)
    st.markdown("### ⏱️ Recent searches")
    if ss.recent_searches:
        for i, rec in enumerate(ss.recent_searches[-5:][::-1]):
            if st.button(rec[:32] + ("…" if len(rec) > 32 else ""), key=f"rec_{i}", width="stretch"):
                queue(rec)
                st.rerun()
    else:
        st.caption("Your searches will appear here.")

tab_trip, tab_lines, tab_about = st.tabs(["🧭 Biyahe", "🚆 Mga linya", "ℹ️ Tungkol"])

# ---------------------------------------------------------------- trip tab
with tab_trip:
    with st.form("picker", border=True):
        st.markdown("**Pumili ng istasyon** -- or just type below.")
        f1, f2 = st.columns(2)
        o_pick = f1.selectbox("Galing (from)", STATIONS, index=None, placeholder="Search a station…")
        d_pick = f2.selectbox("Papunta (to)", STATIONS, index=None, placeholder="Search a station…")
        f3, f4 = st.columns([3, 2])
        pref_pick = f3.radio("Priority", list(MODE_LABELS), format_func=lambda k: MODE_LABELS[k],
                             horizontal=True)
        avoid_pick = f4.multiselect("Iwasan (avoid)", ["Train", "Bus", "Jeepney", "UV Express"])
        if st.form_submit_button("🔎 Hanapin ang ruta", type="primary", width="stretch"):
            if o_pick and d_pick:
                queue(f"{o_pick} → {d_pick}", {"origin": o_pick, "destination": d_pick,
                                              "preference": pref_pick, "avoid": avoid_pick})
            else:
                st.warning("Pumili ng pinanggalingan at pupuntahan.")

    st.markdown("💡 **Subukan:**")
    examples = [("Cubao → Divisoria", "Paano pumunta galing Cubao hanggang Divisoria?"),
                ("Katipunan → NAIA", "Paano pumunta galing Katipunan hanggang NAIA?"),
                ("Monumento → MOA", "Monumento to MOA, kaunting lipat"),
                ("LRT-2 stops", "Anong mga hinto ng LRT-2?")]
    for col, (label, p) in zip(st.columns(len(examples)), examples):
        col.button(label, on_click=queue, args=(p,), width="stretch")

    last_idx = len(ss.messages) - 1
    for i, msg in enumerate(ss.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            payload, debug = msg.get("payload"), msg.get("debug")
            stale = payload and any("stops" not in o for o in payload.get("options", []))
            if msg["role"] != "assistant" or not payload or stale or i != last_idx:
                continue
            if "line" in payload:
                render_line(payload["line"])
            else:
                opts = payload["options"]
                if len(opts) > 1:
                    cols = st.columns(len(opts))
                    for col, opt in zip(cols, opts):
                        with col:
                            star = "⭐ " if opt is payload["best"] else ""
                            labels = " · ".join(MODE_LABELS.get(m, m) for m in opt["modes"])
                            st.markdown(f'<div class="card" style="text-align:center">'
                                        f'<b>{star}{html.escape(labels)}</b><br>'
                                        f'~{opt["mins"]} min · {opt["stops"]} hinto · {opt["transfers"]} lipat'
                                        f'</div>', unsafe_allow_html=True)
                for opt in opts:
                    render_itinerary(opt)
                st.caption("⏱️ Rough estimates only -- no live traffic or schedules.")
            if debug and debug.get("raw"):
                with st.expander("🤖 Local AI -- what the model said"):
                    st.code(debug["raw"], language="json")
                    st.json(debug["result"] or {"status": debug["status"]})

    if ss.messages and ss.messages[-1]["role"] == "assistant":
        a1, a2, a3 = st.columns(3)
        last = ss.messages[-1]
        if a1.button("🔊 Pakinggan", key="listen_btn", width="stretch"):
            speak(last["content"])
        if a2.button("📤 WhatsApp", key="share_btn", width="stretch"):
            st.link_button("Open WhatsApp", "https://wa.me/?text=" + urllib.parse.quote(last["content"]))
        if a3.button("📱 QR code", key="qr_btn", width="stretch"):
            buf = qr_image(last.get("qr_text") or last["content"])
            if buf:
                st.image(buf, caption="Scan to read these directions", width=220)

    typed = st.chat_input("Saan ka pupunta? (hal. Paano pumunta galing Cubao hanggang Divisoria?)")

# ---------------------------------------------------------------- lines tab
with tab_lines:
    trains = [r for r in RIDE_ROUTES if r["type"] == "Train"]
    st.markdown("### 🚆 Tren")
    for col, r in zip(st.columns(len(trains)), trains):
        with col:
            render_line(r)
    st.markdown("### 🚌 Bus, jeep at UV")
    others = [r for r in RIDE_ROUTES if r["type"] != "Train"]
    kinds = st.multiselect("Show", sorted({r["type"] for r in others}),
                           default=sorted({r["type"] for r in others}))
    for r in others:
        if r["type"] in kinds:
            render_line(r, compact=True)

# ---------------------------------------------------------------- about tab
with tab_about:
    st.markdown("""
**Paano Pumunta AI** is an offline commute helper for Metro Manila.

- **Routes are chosen by a deterministic router** (Dijkstra over the stop graph). The local AI only
  interprets your message and optionally rephrases the answer; a faithfulness check discards it if it
  invents anything.
- **Rail data** (LRT-1, LRT-2, MRT-3) uses the real station order. **EDSA Carousel** stops may change.
- **Jeepney and UV routes are marked _unverified_** -- confirm with the driver or terminal. They are only
  used when no verified route exists.
- **No fares, by design.** Fares change often; ask the driver or check the operator.
- Times are rough estimates (no live traffic or schedules).

Add routes in `routes.json`, reusing exact stop names so transfers connect. Use `"type": "Walk"` entries
to link nearby stops.
""")

# ---------------------------------------------------------------- handle input
prompt = typed or ss.pop("queued", None)
forced = None if typed else ss.pop("queued_forced", None)
if typed:
    queue(typed)
    ss.pop("queued", None)
    ss.pop("queued_forced", None)

if prompt:
    t0 = time.time()
    text, payload, debug = answer(prompt, forced)
    ss.latency = time.time() - t0
    ss.request_count += 1
    ss.messages.append({"role": "user", "content": prompt})
    ss.messages.append({"role": "assistant", "content": text, "payload": payload,
                        "debug": debug, "qr_text": (payload or {}).get("facts")})
    st.rerun()
