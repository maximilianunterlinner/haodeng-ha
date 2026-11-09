/*
 * Hao Deng Light Card
 * A colour-wheel light card in the style of the Hao Deng app:
 *   outer ring  = colour (angle = hue, distance = saturation)
 *   inner disc  = white, warm (left) to cool (right)
 *   presets, brightness slider, power button.
 *
 * Works with any Home Assistant light entity that supports RGB/HS and/or colour temperature.
 *
 *   type: custom:haodeng-light-card
 *   entity: light.kuche
 *   name: Küche            # optional
 *   presets:               # optional, max. 6
 *     - color_temp_kelvin: 2700
 *     - rgb_color: [0, 0, 255]
 *     - rgb_color: [255, 120, 0]
 *       brightness_pct: 40
 */

const CARD_VERSION = "1.2.0";
const THROTTLE_MS = 350; // the BLE mesh does not like command floods

const DEFAULT_PRESETS = [
  { color_temp_kelvin: 2700 },
  { rgb_color: [0, 0, 255] },
  { rgb_color: [160, 255, 60] },
  { rgb_color: [255, 110, 30] },
];

const STRINGS = {
  de: { brightness: "Helligkeit", warm: "Warmweiß", cool: "Kaltweiß", unavailable: "Nicht verfügbar", off: "Aus" },
  en: { brightness: "Brightness", warm: "Warm white", cool: "Cool white", unavailable: "Unavailable", off: "Off" },
};

// ---------------------------------------------------------------- colour helpers

function hsvToRgb(h, s, v = 1) {
  const f = (n) => {
    const k = (n + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
  };
  return [f(5), f(3), f(1)].map((x) => Math.round(x * 255));
}

function rgbToHs([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
  }
  h = (h * 60 + 360) % 360;
  return [h, max ? d / max : 0];
}

// Approximation of a black body colour (Tanner Helland), good enough for swatches
function kelvinToRgb(k) {
  const t = k / 100;
  let r, g, b;
  if (t <= 66) {
    r = 255;
    g = 99.47 * Math.log(t) - 161.12;
    b = t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  } else {
    r = 329.7 * Math.pow(t - 60, -0.1332);
    g = 288.12 * Math.pow(t - 60, -0.0755);
    b = 255;
  }
  return [r, g, b].map((x) => Math.round(Math.max(0, Math.min(255, x))));
}

const css = (rgb) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

// Hue 0 (red) sits at 9 o'clock like in the app; hue grows clockwise.
const HUE_OFFSET = 270;

class HaoDengLightCard extends HTMLElement {
  static getStubConfig(hass) {
    const light = Object.keys(hass?.states || {}).find((id) => id.startsWith("light."));
    return { entity: light || "light.example" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "light" } } },
        { name: "name", selector: { text: {} } },
      ],
    };
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { presets: DEFAULT_PRESETS, ...config };
    this._built = false;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, rows: 9, min_columns: 6, min_rows: 7 };
  }

  // ------------------------------------------------------------------ state

  get _stateObj() {
    return this._hass?.states?.[this._config.entity];
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return STRINGS[lang] || STRINGS.en;
  }

  _kelvinRange() {
    const a = this._stateObj?.attributes || {};
    return [a.min_color_temp_kelvin || 2700, a.max_color_temp_kelvin || 6500];
  }

  _supports(mode) {
    const modes = this._stateObj?.attributes?.supported_color_modes || [];
    if (mode === "color") return modes.some((m) => ["hs", "rgb", "rgbw", "rgbww", "xy"].includes(m));
    if (mode === "ct") return modes.includes("color_temp") || modes.includes("rgbww");
    return true;
  }

  // ------------------------------------------------------------- services

  _call(data, service = "turn_on") {
    return this._hass.callService("light", service, { entity_id: this._config.entity, ...data });
  }

  // Leading + trailing throttle: send immediately, then at most every THROTTLE_MS, always send the last value
  _throttled(key, data) {
    this._pending = this._pending || {};
    this._timers = this._timers || {};
    this._pending[key] = data;
    if (this._timers[key]) return;
    const flush = () => {
      const next = this._pending[key];
      this._pending[key] = null;
      if (next) {
        this._call(next);
        this._timers[key] = setTimeout(flush, THROTTLE_MS);
      } else {
        this._timers[key] = null;
      }
    };
    flush();
  }

  // ---------------------------------------------------------------- render

  _build() {
    const t = this._t;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 16px; box-sizing: border-box; overflow: hidden; }
        .header { display: flex; align-items: center; gap: 12px; }
        .title { flex: 1; min-width: 0; }
        .name { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color);
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .sub { font-size: 0.85rem; color: var(--secondary-text-color); margin-top: 2px; }
        .rgb { display: flex; gap: 4px; font: 500 0.75rem/1 var(--code-font-family, monospace); }
        .rgb span { padding: 3px 6px; border-radius: 4px; color: #fff; min-width: 2.6em; text-align: center; }
        .power { width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
                 display: grid; place-items: center; transition: background .2s, color .2s;
                 background: var(--secondary-background-color, #e0e0e0); color: var(--secondary-text-color); }
        .power.on { background: var(--light-color, var(--state-light-active-color, #ffb300)); color: #fff; }
        .power svg { width: 24px; height: 24px; }

        .wheel-wrap { display: flex; justify-content: center; margin: 18px 0 8px; }
        .wheel { position: relative; width: min(100%, 300px); aspect-ratio: 1; border-radius: 50%;
                 touch-action: none; cursor: crosshair; user-select: none; -webkit-user-select: none;
                 background:
                   radial-gradient(circle closest-side, rgba(255,255,255,.85) 50%, rgba(255,255,255,0) 100%),
                   conic-gradient(from ${HUE_OFFSET}deg, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00);
                 box-shadow: 0 0 0 1px rgba(0,0,0,.08), 0 4px 18px rgba(0,0,0,.18); }
        .inner { position: absolute; inset: 25%; border-radius: 50%; overflow: hidden; display: flex;
                 box-shadow: 0 0 0 3px var(--ha-card-background, var(--card-background-color, #fff)); }
        .inner .half { flex: 1; display: flex; flex-direction: column; justify-content: center;
                       align-items: center; text-align: center; color: #333; font-weight: 700;
                       font-size: clamp(.6rem, 2.6vw, .85rem); letter-spacing: .03em; line-height: 1.15; }
        .inner .warm { background: linear-gradient(90deg, ${css(kelvinToRgb(2700))}, ${css(kelvinToRgb(4300))}); }
        .inner .cool { background: linear-gradient(90deg, ${css(kelvinToRgb(4300))}, ${css(kelvinToRgb(9000))}); }
        .inner .half small { font-weight: 500; opacity: .75; }
        .marker { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
                  border: 3px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,.35), 0 2px 6px rgba(0,0,0,.4);
                  pointer-events: none; transition: left .15s, top .15s; }
        .marker[hidden] { display: none; }

        .presets { display: grid; grid-template-columns: repeat(auto-fit, minmax(44px, 1fr)); gap: 10px; margin: 14px 0 6px; }
        .preset { height: 44px; border-radius: 10px; border: 2px solid rgba(255,255,255,.6); cursor: pointer;
                  box-shadow: 0 1px 4px rgba(0,0,0,.25); font: 500 .75rem system-ui; color: rgba(0,0,0,.55);
                  display: flex; align-items: flex-end; justify-content: center; padding-bottom: 3px; }
        .preset:active { transform: scale(.95); }

        .bright { margin-top: 12px; }
        .bright label { display: flex; justify-content: space-between; color: var(--primary-text-color);
                        font-size: .95rem; margin-bottom: 6px; }
        input[type=range] { width: 100%; height: 28px; margin: 0; accent-color: var(--primary-color);
                            -webkit-appearance: none; appearance: none; background: transparent; cursor: pointer; }
        input[type=range]::-webkit-slider-runnable-track { height: 8px; border-radius: 4px;
          background: linear-gradient(90deg, #333, var(--bright-color, #fff)); }
        input[type=range]::-moz-range-track { height: 8px; border-radius: 4px;
          background: linear-gradient(90deg, #333, var(--bright-color, #fff)); }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 24px; height: 24px; margin-top: -8px;
          border-radius: 50%; background: #fff; border: 2px solid var(--primary-color); box-shadow: 0 1px 4px rgba(0,0,0,.4); }
        input[type=range]::-moz-range-thumb { width: 22px; height: 22px; border-radius: 50%; background: #fff;
          border: 2px solid var(--primary-color); }

        .disabled .wheel, .disabled .presets, .disabled .bright { opacity: .35; pointer-events: none; filter: grayscale(.6); }
      </style>
      <ha-card>
        <div class="root">
          <div class="header">
            <div class="title">
              <div class="name"></div>
              <div class="sub"></div>
            </div>
            <div class="rgb"><span style="background:#c62828">R 0</span><span style="background:#2e7d32">G 0</span><span style="background:#1565c0">B 0</span></div>
            <button class="power" title="Ein/Aus">
              <svg viewBox="0 0 24 24"><path fill="currentColor" d="M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,9.28 18.64,6.88 16.56,5.44M13,3H11V13H13"/></svg>
            </button>
          </div>
          <div class="wheel-wrap">
            <div class="wheel">
              <div class="inner">
                <div class="half warm" title="${t.warm}">WARM<small>WHITE</small></div>
                <div class="half cool" title="${t.cool}">COOL<small>WHITE</small></div>
              </div>
              <div class="marker" hidden></div>
            </div>
          </div>
          <div class="presets"></div>
          <div class="bright">
            <label><span>${t.brightness}</span><span class="pct">–</span></label>
            <input type="range" min="1" max="100" step="1">
          </div>
        </div>
      </ha-card>`;

    const $ = (s) => this.shadowRoot.querySelector(s);
    this._el = {
      root: $(".root"), name: $(".name"), sub: $(".sub"), rgb: this.shadowRoot.querySelectorAll(".rgb span"),
      power: $(".power"), wheel: $(".wheel"), inner: $(".inner"), marker: $(".marker"),
      presets: $(".presets"), slider: $("input"), pct: $(".pct"),
    };

    this._el.power.addEventListener("click", () => this._call({}, "toggle"));

    // Wheel interaction
    const wheel = this._el.wheel;
    wheel.addEventListener("pointerdown", (ev) => {
      wheel.setPointerCapture(ev.pointerId);
      this._dragging = true;
      this._pick(ev);
    });
    wheel.addEventListener("pointermove", (ev) => this._dragging && this._pick(ev));
    const end = () => (this._dragging = false);
    wheel.addEventListener("pointerup", end);
    wheel.addEventListener("pointercancel", end);

    // Brightness
    this._el.slider.addEventListener("input", () => {
      this._sliding = true;
      const v = Number(this._el.slider.value);
      this._el.pct.textContent = `${v}%`;
      this._throttled("brightness", { brightness_pct: v });
    });
    this._el.slider.addEventListener("change", () => {
      this._sliding = false; // the throttle already delivers the final value of the drag
    });

    this._buildPresets();
    this._built = true;
  }

  _buildPresets() {
    const box = this._el.presets;
    box.innerHTML = "";
    for (const preset of (this._config.presets || []).slice(0, 6)) {
      const b = document.createElement("button");
      b.className = "preset";
      const rgb = preset.rgb_color || (preset.color_temp_kelvin ? kelvinToRgb(preset.color_temp_kelvin) : [255, 255, 255]);
      b.style.background = css(rgb);
      if (preset.brightness_pct) b.textContent = `${preset.brightness_pct}%`;
      b.title = preset.color_temp_kelvin ? `${preset.color_temp_kelvin} K` : `RGB ${rgb.join(", ")}`;
      b.addEventListener("click", () => this._call({ ...preset }));
      box.appendChild(b);
    }
    box.hidden = box.children.length === 0;
  }

  _geometry() {
    const r = this._el.wheel.getBoundingClientRect();
    return { r, cx: r.left + r.width / 2, cy: r.top + r.height / 2, R: r.width / 2, Ri: r.width / 4 };
  }

  _pick(ev) {
    const { r, cx, cy, R, Ri } = this._geometry();
    const dx = ev.clientX - cx, dy = ev.clientY - cy;
    const dist = Math.hypot(dx, dy);
    if (dist > R + 4) return;

    if (dist <= Ri + 2) {
      if (!this._supports("ct")) return;
      // Inner disc: x position from warm (left) to cool (right)
      const [kMin, kMax] = this._kelvinRange();
      const ratio = Math.min(1, Math.max(0, (ev.clientX - (cx - Ri)) / (2 * Ri)));
      const kelvin = Math.round(kMin + ratio * (kMax - kMin));
      this._showMarker(ev.clientX - r.left, ev.clientY - r.top, kelvinToRgb(kelvin));
      this._throttled("color", { color_temp_kelvin: kelvin });
    } else {
      if (!this._supports("color")) return;
      const angle = (Math.atan2(dx, -dy) * 180) / Math.PI; // 0 = top, clockwise
      const hue = (angle - HUE_OFFSET + 720) % 360;
      const sat = Math.min(1, Math.max(0.15, (Math.min(dist, R) - Ri) / (R - Ri)));
      const rgb = hsvToRgb(hue, sat);
      this._showMarker(ev.clientX - r.left, ev.clientY - r.top, rgb);
      this._throttled("color", { hs_color: [Math.round(hue), Math.round(sat * 100)] });
    }
    this._lastPick = Date.now();
  }

  _showMarker(x, y, rgb) {
    const m = this._el.marker;
    m.hidden = false;
    m.style.left = `${x}px`;
    m.style.top = `${y}px`;
    m.style.background = css(rgb);
  }

  _markerFromState(st) {
    const a = st.attributes;
    const size = this._el.wheel.clientWidth;
    if (!size) return;
    const R = size / 2, Ri = size / 4;
    if (st.state !== "on") {
      this._el.marker.hidden = true;
      return;
    }
    if (a.color_mode === "color_temp" && a.color_temp_kelvin) {
      const [kMin, kMax] = this._kelvinRange();
      const ratio = Math.min(1, Math.max(0, (a.color_temp_kelvin - kMin) / (kMax - kMin)));
      this._showMarker(R - Ri * 0.8 + ratio * 1.6 * Ri, R + Ri * 0.55, kelvinToRgb(a.color_temp_kelvin));
    } else if (a.hs_color) {
      const [h, s] = a.hs_color;
      const angle = ((h + HUE_OFFSET) * Math.PI) / 180;
      const dist = Ri + (Math.max(0.15, s / 100)) * (R - Ri) * 0.94;
      this._showMarker(R + Math.sin(angle) * dist, R - Math.cos(angle) * dist, hsvToRgb(h, s / 100));
    }
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this._built) this._build();
    const st = this._stateObj;
    const t = this._t;
    const el = this._el;

    el.name.textContent = this._config.name || st?.attributes?.friendly_name || this._config.entity;
    const unavailable = !st || st.state === "unavailable";
    el.root.classList.toggle("disabled", unavailable);
    el.inner.style.display = this._supports("ct") ? "" : "none";
    if (unavailable) {
      el.sub.textContent = t.unavailable;
      el.power.classList.remove("on");
      return;
    }

    const on = st.state === "on";
    const a = st.attributes;
    const pct = a.brightness != null ? Math.max(1, Math.round((a.brightness / 255) * 100)) : null;
    const rgb = a.rgb_color || (a.color_temp_kelvin ? kelvinToRgb(a.color_temp_kelvin) : [255, 255, 255]);

    el.power.classList.toggle("on", on);
    el.power.style.setProperty("--light-color", on ? css(rgb) : "");
    el.sub.textContent = on
      ? a.color_mode === "color_temp" && a.color_temp_kelvin ? `${a.color_temp_kelvin} K · ${pct ?? "–"}%` : `${pct ?? "–"}%`
      : t.off;
    const shown = on ? rgb : [0, 0, 0];
    ["R", "G", "B"].forEach((c, i) => (el.rgb[i].textContent = `${c} ${shown[i]}`));

    if (!this._sliding) {
      el.slider.value = pct ?? 100;
      el.pct.textContent = on && pct != null ? `${pct}%` : "–";
    }
    el.slider.style.setProperty("--bright-color", css(rgb));

    // Don't fight the user's finger: only follow the state when not picking right now
    if (!this._dragging && Date.now() - (this._lastPick || 0) > 1500) this._markerFromState(st);
  }
}

if (!customElements.get("haodeng-light-card")) {
  customElements.define("haodeng-light-card", HaoDengLightCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "haodeng-light-card",
    name: "Hao Deng Licht",
    description: "Farbrad mit Warm-/Kaltweiß, Schnellwahl und Helligkeit – wie in der Hao-Deng-App.",
    preview: true,
    documentationURL: "https://github.com/maximilianunterlinner/haodeng-ha",
  });
  console.info(`%c HAODENG-LIGHT-CARD %c ${CARD_VERSION} `, "background:#1565c0;color:#fff", "");
}
