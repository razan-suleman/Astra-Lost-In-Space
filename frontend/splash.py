"""Splash (intro) screen shown before the dashboard.

What's on it:
- a starry background
- a spinning globe: a circle with a flat world map (static/splash_land.svg)
  scrolling sideways inside it, plus shading so it looks round
- two satellites (MODIS and VIIRS) on tilted orbits; real 3D CSS transforms,
  so they pass behind the globe and in front of it
- a Start button: semi-transparent, fades to full opacity on hover

It's all HTML + CSS (no JavaScript), drawn with st.markdown. The Start button
is a real Streamlit button, styled and moved to the middle of the screen with
CSS through its key class (.st-key-start_btn).

To change the look, edit the CSS variables at the top of _CSS.
"""

from __future__ import annotations

import streamlit as st

LAND_URL = "app/static/splash_land.svg"

# One satellite drawing, reused for both. Width 44, height 22.
_SATELLITE_SVG = (
    '<svg viewBox="0 0 44 22" width="44" height="22" aria-hidden="true">'
    '<rect x="0.5" y="7" width="14" height="8" rx="1" fill="#3987e5" stroke="#cde2fb" stroke-width="0.8"/>'
    '<line x1="5" y1="7" x2="5" y2="15" stroke="#cde2fb" stroke-width="0.5"/>'
    '<line x1="10" y1="7" x2="10" y2="15" stroke="#cde2fb" stroke-width="0.5"/>'
    '<rect x="29.5" y="7" width="14" height="8" rx="1" fill="#3987e5" stroke="#cde2fb" stroke-width="0.8"/>'
    '<line x1="34" y1="7" x2="34" y2="15" stroke="#cde2fb" stroke-width="0.5"/>'
    '<line x1="39" y1="7" x2="39" y2="15" stroke="#cde2fb" stroke-width="0.5"/>'
    '<line x1="14.5" y1="11" x2="29.5" y2="11" stroke="#c3c2b7" stroke-width="1"/>'
    '<rect x="16" y="4" width="12" height="14" rx="2" fill="#f0efec" stroke="#898781" stroke-width="0.6"/>'
    '<circle cx="22" cy="2.5" r="1.5" fill="#f0efec"/>'
    "</svg>"
)

_CSS = """
<style>
/* ---- Look & feel: change these ---------------------------------------- */
.fx-splash {
  --d: min(56vh, 56vw);          /* globe diameter */
  --sky-top: #0b1a33;
  --sky-bottom: #02060f;
  --ocean: #1d4f8a;
  --spin-time: 60s;              /* one full turn of the globe */
  --orbit1-time: 26s;            /* MODIS satellite */
  --orbit2-time: 38s;            /* VIIRS satellite */
}

/* ---- Hide the normal Streamlit chrome while the splash is up ---------- */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }

/* ---- Background with stars ---------------------------------------------- */
.fx-splash {
  position: fixed; inset: 0; z-index: 999;
  overflow: hidden;
  background:
    radial-gradient(1px 1px at 12% 18%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 78% 12%, #fff 50%, transparent 51%),
    radial-gradient(1.5px 1.5px at 30% 72%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 88% 64%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 55% 90%, #fff 50%, transparent 51%),
    radial-gradient(1.5px 1.5px at 6% 52%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 66% 34%, #fff 50%, transparent 51%),
    radial-gradient(1px 1px at 22% 40%, rgba(255,255,255,.7) 50%, transparent 51%),
    radial-gradient(1px 1px at 94% 88%, rgba(255,255,255,.7) 50%, transparent 51%),
    radial-gradient(1px 1px at 42% 8%, rgba(255,255,255,.7) 50%, transparent 51%),
    radial-gradient(ellipse at 50% 40%, var(--sky-top), var(--sky-bottom) 75%);
  background-size: 360px 360px, 420px 420px, 380px 380px, 300px 300px, 460px 460px,
                   340px 340px, 500px 500px, 260px 260px, 320px 320px, 280px 280px, 100% 100%;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #f0efec;
}

/* ---- Title ---------------------------------------------------------------- */
.fx-title {
  position: absolute; top: 6vh; left: 0; right: 0; text-align: center;
  padding: 0 1rem; pointer-events: none;
}
.fx-title h1 {
  margin: 0; font-size: clamp(1.6rem, 3.6vw, 3rem); font-weight: 700;
  letter-spacing: -0.01em; color: #f0efec; padding: 0;
}
.fx-title p {
  margin: .6rem 0 0; font-size: clamp(.9rem, 1.4vw, 1.1rem); color: #c3c2b7;
}

/* ---- 3D scene: globe + orbits share one 3D space -------------------------- */
.fx-scene {
  position: absolute; left: 50%; top: 58%;
  width: var(--d); height: var(--d);
  margin-left: calc(var(--d) / -2); margin-top: calc(var(--d) / -2);
  perspective: 1400px; transform-style: preserve-3d;
}
.fx-globe {
  position: absolute; inset: 0; border-radius: 50%;
  background-color: var(--ocean);
  background-image: url("LAND_URL");
  background-repeat: repeat-x;
  background-size: calc(var(--d) * 2) var(--d);
  animation: fx-turn var(--spin-time) linear infinite;
}
/* Atmosphere glow: a separate flat element behind the 3D scene. Putting the
   glow on the globe itself makes browsers clip it to a square. */
.fx-glow {
  position: absolute; left: 50%; top: 58%;
  width: calc(var(--d) * 1.3); height: calc(var(--d) * 1.3);
  transform: translate(-50%, -50%); border-radius: 50%;
  background: radial-gradient(circle, rgba(90,160,255,.38) 0%, rgba(90,160,255,.12) 42%, transparent 66%);
  pointer-events: none;
}
/* Shading on top of the map so it reads as a sphere */
.fx-globe::after {
  content: ""; position: absolute; inset: 0; border-radius: 50%;
  background:
    radial-gradient(circle at 32% 28%, rgba(255,255,255,.28), transparent 42%),
    radial-gradient(circle at 50% 50%, transparent 58%, rgba(0,0,0,.55) 100%);
  box-shadow: inset calc(var(--d) * -.08) calc(var(--d) * -.06) calc(var(--d) * .14) rgba(0,0,0,.6);
}
@keyframes fx-turn { from { background-position: 0 0; } to { background-position: calc(var(--d) * -2) 0; } }

/* ---- Orbits ----------------------------------------------------------------
   .fx-orbit tilts the orbit plane, .fx-spin turns around it, and .fx-sat turns
   back the other way so the satellite always faces the viewer. */
.fx-orbit {
  position: absolute; inset: calc(var(--d) * -0.32);
  transform-style: preserve-3d;
}
.fx-o1 { transform: rotateZ(-16deg) rotateX(74deg); }
.fx-o2 { transform: rotateZ(22deg) rotateX(68deg); inset: calc(var(--d) * -0.22); }
.fx-ring {
  position: absolute; inset: 0; border-radius: 50%;
  border: 1px dashed rgba(205, 226, 251, .22);
}
.fx-spin { position: absolute; inset: 0; transform-style: preserve-3d; }
.fx-o1 .fx-spin { animation: fx-spin var(--orbit1-time) linear infinite; }
.fx-o2 .fx-spin { animation: fx-spin var(--orbit2-time) linear infinite reverse; }
@keyframes fx-spin { from { transform: rotateZ(0deg); } to { transform: rotateZ(360deg); } }

.fx-sat {
  position: absolute; top: -11px; left: 50%; margin-left: -22px;
  width: 44px; height: 22px; text-align: center;
}
.fx-o1 .fx-sat { animation: fx-face1 var(--orbit1-time) linear infinite; }
.fx-o2 .fx-sat { animation: fx-face2 var(--orbit2-time) linear infinite reverse; }
@keyframes fx-face1 {
  from { transform: rotateZ(0deg)    rotateX(-74deg) rotateZ(16deg); }
  to   { transform: rotateZ(-360deg) rotateX(-74deg) rotateZ(16deg); }
}
@keyframes fx-face2 {
  from { transform: rotateZ(0deg)    rotateX(-68deg) rotateZ(-22deg); }
  to   { transform: rotateZ(-360deg) rotateX(-68deg) rotateZ(-22deg); }
}
.fx-sat span {
  display: block; margin-top: 2px; font-size: 10px; letter-spacing: .08em;
  color: #cde2fb; white-space: nowrap;
}

/* ---- Start button (a real st.button, moved to the middle) ----------------- */
.st-key-start_btn {
  position: fixed; left: 50%; top: 58%; transform: translate(-50%, -50%);
  z-index: 1000; width: auto !important;
}
.st-key-start_btn button {
  opacity: .55;
  background: rgba(8, 20, 44, .55);
  border: 1.5px solid rgba(255, 255, 255, .8);
  border-radius: 999px;
  padding: .85rem 3.2rem;
  transition: opacity .45s ease, transform .45s ease, box-shadow .45s ease, background .45s ease;
}
.st-key-start_btn button p {
  color: #ffffff; font-size: 1.3rem; font-weight: 600; letter-spacing: .12em;
}
.st-key-start_btn button:hover,
.st-key-start_btn button:focus-visible {
  opacity: 1;
  transform: scale(1.06);
  background: rgba(20, 50, 100, .75);
  border-color: #ffffff;
  box-shadow: 0 0 28px rgba(140, 190, 255, .55);
  color: #ffffff;
}
.st-key-start_btn button:active { transform: scale(.98); }

/* ---- Footer hint ---------------------------------------------------------- */
.fx-foot {
  position: absolute; bottom: 3vh; left: 0; right: 0; text-align: center;
  font-size: .8rem; color: #898781; pointer-events: none;
}

/* People who turn off animations in their OS settings get a still image. */
@media (prefers-reduced-motion: reduce) {
  .fx-globe, .fx-spin, .fx-sat { animation: none !important; }
}
</style>
""".replace("LAND_URL", LAND_URL)

_HTML = f"""
<div class="fx-splash">
<div class="fx-title">
<h1>Harmonized Burning Activity Calendar</h1>
<p>Two decades of fire hotspots from MODIS and VIIRS, joined into one consistent record</p>
</div>
<div class="fx-glow"></div>
<div class="fx-scene">
<div class="fx-orbit fx-o1"><div class="fx-ring"></div><div class="fx-spin">
<div class="fx-sat">{_SATELLITE_SVG}<span>MODIS</span></div></div></div>
<div class="fx-globe"></div>
<div class="fx-orbit fx-o2"><div class="fx-ring"></div><div class="fx-spin">
<div class="fx-sat">{_SATELLITE_SVG}<span>VIIRS</span></div></div></div>
</div>
<div class="fx-foot">Fire radiative power from NASA active fire products · 2003 to today</div>
</div>
"""


def _start() -> None:
    st.session_state.started = True


def render() -> None:
    """Draw the splash screen. Clicking Start sets st.session_state.started."""
    # No blank lines or indented lines: Markdown would turn them into code blocks.
    st.markdown(_CSS + "".join(line.strip() for line in _HTML.splitlines()), unsafe_allow_html=True)
    st.button("START", key="start_btn", on_click=_start)
