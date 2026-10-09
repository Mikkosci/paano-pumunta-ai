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

from llm import (DEFAULT_MODEL, DEFAULT_URL, FARE_DISCLAIMER,
                 contains_fare_question, interpret, phrase_itinerary,
                 phrasing_is_faithful)
from router import MODE_LABELS, Router, describe_itinerary, load_data

st.set_page_config(page_title="Paano Pumunta AI", page_icon="📍", layout="wide")

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.header { background: linear-gradient(135deg, #1e7e34 0%, #1DB954 100%);
  padding: 25px; border-radius: 15px; text-align: center; margin-bottom: 25px; }
.big-title { color: white !important; font-size: 42px !important; margin: 0 !important; }
.sub-title { color: rgba(255,255,255,0.9) !important; font-size: 18px !important; }
.offline-badge { background: rgba(255,255,255,0.2); color: white; padding: 8px 20px;
  border-radius: 25px; display: inline-block; margin-top: 15px; font-weight: bold; font-size: 14px; }
.opt-head { font-weight: 700; font-size: 16px; margin: 18px 0 6px 0; }
.leg { background: white; color: #222; border-radius: 12px; padding: 12px 15px; margin: 8px 0;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-left: 5px solid #1DB954; }
.leg.walk { border-left-color: #9e9e9e; }
.leg.jeep { border-left-color: #ff9800; }
.leg.uv { border-left-color: #1976d2; }
.tag { background: #1e7e34; color: white; padding: 3px 11px; border-radius: 14px;
  font-size: 12px; font-weight: bold; margin-right: 8px; }
.stops { color: #666; margin: 8px 0 2px 0; font-size: 14px; }
.hl { color: #d32f2f; font-weight: bold; }
.total { background: #e8f5e9; color: #1b5e20; border-radius: 10px; padding: 10px 14px;
  margin: 8px 0; font-weight: 600; }
.xfer { background: #fff3cd; color: #5d4600; border: 2px solid #ffc107; border-radius: 10px;
  padding: 8px 12px; margin: 6px 0; font-size: 14px; }
.difficulty-badge { display: inline-block; padding: 4px 12px; border-radius: 15px;
  font-size: 12px; font-weight: bold; margin-left: 10px; }
.easy { background: #4caf50; color: white; }
.moderate { background: #ff9800; color: white; }
.complex { background: #f44336; color: white; }
.tip-box { background: #fff3e0; border-radius: 12px; padding: 15px; margin: 10px 0;
  border-left: 4px solid #ff9800; color: #333; }
.metric-box { background: #e3f2fd; border-radius: 12px; padding: 15px; margin: 10px 0;
  border-left: 5px solid #1976d2; }
.offline-indicator { background: #e8f5e9; border-radius: 10px; padding: 12px 16px;
  margin: 15px 0; border-left: 4px solid #1DB954; color: #1b5e20; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header">
    <div style="font-size:56px;">🚏</div>
    <h1 class="big-title">Paano pumunta?</h1>
    <p class="sub-title">A Community Guide for Commuters PH</p>
    <div class="offline-badge">📴 Works Offline • Local AI • Taglish Ready</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="offline-indicator">
    ✅ <strong>Offline Mode Active</strong><br>
    <small>Routes are computed on this device. No internet needed for directions.</small>
</div>
""", unsafe_allow_html=True)


@st.cache_resource
def get_router():
    return Router(load_data("routes.json"))


router = get_router()

TYPE_ICON = {"Train": "🚆", "Jeepney": "🚌", "UV Express": "🚐", "Walk": "🚶"}
TYPE_CLASS = {"Walk": "walk", "Jeepney": "jeep", "UV Express": "uv"}

# ---------------------------------------------------------------- state
ss = st.session_state
ss.setdefault("messages", [])
ss.setdefault("request_count", 0)
ss.setdefault("latency", None)
ss.setdefault("ai_mode", "—")
ss.setdefault("font_size", "Medium")
ss.setdefault("recent_searches", [])
ss.setdefault("last_trip", None)


def queue(p):
    ss["queued"] = p
    if p not in ss["recent_searches"]:
        ss["recent_searches"].append(p)
        if len(ss["recent_searches"]) > 10:
            ss["recent_searches"] = ss["recent_searches"][-10:]


def get_difficulty(opt):
    transfers = opt["transfers"]
    if transfers == 0:
        return "⭐ Easy", "easy"
    if transfers == 1:
        return "⭐⭐ Moderate", "moderate"
    return "⭐⭐⭐ Complex", "complex"


def _js_str(s):
    return json.dumps(s).replace("<", "\\u003c")


def speak(text):
    """Read text aloud via the browser's built-in (on-device) speech synthesis."""
    cleaned = re.sub(r"[*_`#]", "", text)
    components.html(
        "<script>var u=new SpeechSynthesisUtterance(" + _js_str(cleaned) + ");"
        "u.lang='fil-PH';speechSynthesis.cancel();speechSynthesis.speak(u);</script>",
        height=0)


def qr_image(text):
    """QR code encoding the actual route text."""
    try:
        qr = qrcode.make(text)
        buf = BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


# ---------------------------------------------------------------- render
def render_itinerary(origin, dest, opt):
    modes = " / ".join(MODE_LABELS[m] for m in opt["modes"])
    difficulty_text, diff_class = get_difficulty(opt)
    st.markdown(
        f'<div class="opt-head">✅ {html.escape(modes)} '
        f'<span class="difficulty-badge {diff_class}">{difficulty_text}</span></div>',
        unsafe_allow_html=True)
    st.markdown(
        f'<div class="tip-box">⏰ <strong>Oras:</strong> mga {opt["mins"]} min '
        f'<em>(rough estimate)</em> · {opt["stops"]} hinto · {opt["transfers"]} lipat</div>',
        unsafe_allow_html=True)
    for i, leg in enumerate(opt["legs"]):
        icon = TYPE_ICON.get(leg["type"], "🚏")
        stops = [html.escape(s) for s in leg["stops"]]
        stops[0] = f"<b>{stops[0]}</b>"
        stops[-1] = f'<span class="hl">{stops[-1]}</span>'
        st.markdown(f"""
        <div class="leg {TYPE_CLASS.get(leg['type'], '')}">
          <span class="tag">{icon} {html.escape(leg['type'])}</span>
          <strong>{html.escape(leg['route'])}</strong>
          <div class="stops">{' → '.join(stops)}</div>
          <small style="color:#888">{leg['hops']} hinto · ~{leg['mins']} min (rough estimate) ·
          {html.escape(leg['details'])}</small>
        </div>""", unsafe_allow_html=True)
        if i < len(opt["legs"]) - 1:
            st.markdown(f'<div class="xfer">🔄 Lipat dito: <b>{html.escape(leg["to"])}</b></div>',
                        unsafe_allow_html=True)
    st.markdown(f'<div class="total">Kabuuan: {opt["stops"]} hinto · '
                f'mga {opt["mins"]} min (rough estimate) · {opt["transfers"]} lipat</div>',
                unsafe_allow_html=True)


def render_line(route):
    st.markdown(f"""
    <div class="leg"><span class="tag">{TYPE_ICON.get(route['type'], '🚏')} {html.escape(route['type'])}</span>
    <strong>{html.escape(route['name'])}</strong>
    <div class="stops">{' → '.join(html.escape(s) for s in route['stops'])}</div>
    <small style="color:#888">{html.escape(route.get('details', ''))}</small></div>""",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- answer
def answer(prompt):
    """Return (text, payload, debug) for a user prompt.

    The local model interprets the message; the deterministic router is the
    only thing that chooses routes. debug carries the model's raw output for
    the transparency expander.
    """
    interp = interpret(prompt, router, llm_url, llm_model) if use_llm else None
    result = (interp or {}).get("result")

    origin = result["origin"] if result else None
    dest = result["destination"] if result else None
    preference = (result.get("preference") if result else None) or "fastest"
    avoid = result["avoid"] if result else []

    # follow-up ("paano kung walang MRT?", "mas kaunting lipat?"): reuse last trip
    if result and result["follow_up"] and ss.last_trip:
        origin = origin or ss.last_trip["origin"]
        dest = dest or ss.last_trip["destination"]

    # rules-based parser fills whatever the model missed
    q = router.parse_query(prompt)
    if not origin or not dest:
        if q["line"] and not (q["origin"] and q["dest"]) and not origin and not dest:
            r = router.line_info(q["line"])
            if r:
                stops = ", ".join(r["stops"])
                return f"Ito ang mga hinto ng {r['name']}: {stops}.", {"line": r}, interp
        origin = origin or q["origin"]
        dest = dest or q["dest"]
    if not result:
        preference = q["preference"] or preference
        avoid = q["avoid"]
        # rules-only follow-up: "paano kung walang MRT?" with no places named
        if not origin and not dest and (q["avoid"] or q["preference"]) and ss.last_trip:
            origin, dest = ss.last_trip["origin"], ss.last_trip["destination"]

    fare_q = contains_fare_question(prompt)

    if not origin and not dest:
        sample = ", ".join(router.nodes[:12])
        text = ("Hindi ko makita kung saan ka galing o pupunta. Subukan: "
                "'Paano pumunta galing Cubao hanggang Divisoria?'. "
                f"Ilan sa mga lugar na alam ko: {sample}…")
        if fare_q:
            text = FARE_DISCLAIMER + " " + text
        return text, None, interp
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

    interp_status = interp["status"] if interp else "off"
    ss.ai_mode = f"Interpret: {interp_status} · {mode}"
    ss.last_trip = {"origin": origin, "destination": dest}
    payload = {"origin": origin, "destination": dest, "options": options,
               "best": best, "preference": preference, "facts": facts}
    return text, payload, interp


FONT_SIZES = {"Small": "14px", "Medium": "16px", "Large": "18px", "Extra Large": "22px"}
st.markdown(f"<style>body {{ font-size: {FONT_SIZES.get(ss.font_size, '16px')} !important; }}</style>",
            unsafe_allow_html=True)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    use_llm = st.toggle("Use local AI (LM Studio)", value=True)
    llm_url = st.text_input("LM Studio URL", DEFAULT_URL)
    llm_model = st.text_input("Model name", DEFAULT_MODEL)
    st.caption("The model interprets your message and rephrases answers. "
               "Routes are always chosen by the deterministic router.")
    st.divider()

    st.markdown("### 🔤 Font Size")
    selected_font = st.selectbox("Choose size", list(FONT_SIZES.keys()),
                                 index=list(FONT_SIZES.keys()).index(ss.font_size))
    if selected_font != ss.font_size:
        ss.font_size = selected_font
        st.rerun()

    st.divider()
    st.markdown("## 📊 Live Statistics")
    st.metric("Questions answered", ss.request_count)
    st.metric("Routes in database", len(router.routes))
    st.metric("Places known", len(router.nodes))
    st.metric("Last response time", f"{ss.latency:.1f} s" if ss.latency else "—")
    st.write(f"**Answer mode:** {ss.ai_mode}")
    st.divider()

    if st.button("🔄 Reset conversation", width="stretch"):
        ss.messages, ss.request_count, ss.latency, ss.ai_mode = [], 0, None, "—"
        ss.recent_searches, ss.last_trip = [], None
        st.rerun()

    history_text = "\n\n".join(f"{m['role'].title()}: {m['content']}" for m in ss.messages)
    st.download_button("📥 Export Chat History", data=history_text,
                       file_name="paano_pumunta_chat.txt", mime="text/plain",
                       width="stretch", disabled=not ss.messages)

    st.divider()
    with st.expander("💡 Pro Commuter Tips"):
        st.markdown("""
        <div class="tip-box">
            <strong>🕐 Peak Hours:</strong> 7-9 AM and 5-8 PM are super crowded<br>
            <strong>🛡️ Safety:</strong> Keep your phone and wallet secure in crowded jeeps<br>
            <strong>📍 Transfer Tips:</strong> Look for signboards, not just route numbers<br>
            <strong>⏰ Best Time:</strong> Travel before 7 AM or after 8 PM for empty jeeps
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.markdown("### ⏱️ Recent Searches")
    if ss.recent_searches:
        for i, rec in enumerate(ss.recent_searches[-5:][::-1]):
            btn_text = rec[:30] + "..." if len(rec) > 30 else rec
            if st.button(btn_text, key=f"rec_{i}", width="stretch"):
                queue(rec)
                st.rerun()
    else:
        st.caption("Your searches will appear here...")

    with st.expander("📍 Routes in database"):
        for r in router.routes:
            st.write(f"• **{r['name']}** · {r['type']} · {len(r['stops'])} stops")

# ---------------------------------------------------------------- chat history
last_idx = len(ss.messages) - 1
for i, msg in enumerate(ss.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        payload = msg.get("payload")
        debug = msg.get("debug")
        if msg["role"] == "assistant" and payload and i == last_idx:
            if "line" in payload:
                render_line(payload["line"])
            else:
                st.caption("Oras ay rough estimate lang. Maaaring iba sa aktwal.")
                if len(payload["options"]) > 1:
                    st.markdown("### 📊 Compare All Routes")
                    cols = st.columns(len(payload["options"]))
                    for j, opt in enumerate(payload["options"]):
                        with cols[j]:
                            diff_text, _ = get_difficulty(opt)
                            star = "⭐ " if opt is payload["best"] else ""
                            modes = " / ".join(MODE_LABELS[m] for m in opt["modes"])
                            st.markdown(f"""
                            <div class="total" style="text-align:center;">
                                <strong>{star}{j + 1}. {html.escape(modes)}</strong><br>
                                {diff_text}<br>
                                {opt['stops']} hinto · ~{opt['mins']} min<br>
                                {opt['transfers']} lipat
                            </div>""", unsafe_allow_html=True)
                for opt in payload["options"]:
                    render_itinerary(payload["origin"], payload["destination"], opt)
            if debug and debug.get("raw"):
                with st.expander("🤖 Local AI — what the model said"):
                    st.markdown("**Raw model output:**")
                    st.code(debug["raw"], language="json")
                    st.markdown("**Validated result:**")
                    st.json(debug["result"] or {"status": debug["status"]})

# ---------------------------------------------------------------- input
st.markdown("💡 **Try these quick routes:**")
c1, c2, c3, c4 = st.columns(4)
c1.button("Cubao → Divisoria", on_click=queue, args=("Paano pumunta galing Cubao hanggang Divisoria?",),
          width="stretch")
c2.button("Ayala → Washington", on_click=queue, args=("Paano pumunta galing Ayala to Washington?",),
          width="stretch")
c3.button("North Ave → Antipolo", on_click=queue, args=("Paano pumunta galing North Avenue hanggang Antipolo?",),
          width="stretch")
c4.button("MRT-3 Stops", on_click=queue, args=("Anong mga hinto ng MRT-3?",), width="stretch")

typed = st.chat_input("Saan ka pupunta? (e.g., Paano pumunta galing Cubao hanggang Divisoria?)")
prompt = typed or ss.pop("queued", None)
if typed:
    queue(typed)
    ss.pop("queued", None)

if prompt:
    t0 = time.time()
    text, payload, debug = answer(prompt)
    ss.latency = time.time() - t0
    ss.request_count += 1
    ss.messages.append({"role": "user", "content": prompt})
    ss.messages.append({"role": "assistant", "content": text, "payload": payload,
                        "debug": debug, "qr_text": (payload or {}).get("facts")})
    st.rerun()

# ---------------------------------------------------------------- action buttons
if ss.messages and ss.messages[-1]["role"] == "assistant":
    col_listen, col_share, col_qr = st.columns(3)
    with col_listen:
        if st.button("🔊 Listen to Directions", key="listen_btn"):
            speak(ss.messages[-1]["content"])
    with col_share:
        if st.button("📤 Share via WhatsApp", key="share_btn"):
            wa_text = urllib.parse.quote(ss.messages[-1]["content"])
            st.markdown(f'<a href="https://wa.me/?text={wa_text}" target="_blank">'
                        '<div class="tip-box" style="text-align:center;">'
                        '📱 Open WhatsApp with this text</div></a>',
                        unsafe_allow_html=True)
    with col_qr:
        if st.button("📱 QR Code", key="qr_btn"):
            qr_text = ss.messages[-1].get("qr_text") or ss.messages[-1]["content"]
            buf = qr_image(qr_text)
            if buf:
                st.image(buf, caption="Scan to read these directions")
