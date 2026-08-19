// Annika "entity toggle" tile feature.
//
// A native tile feature can only act on the tile's own entity, so there is
// no built-in way to show a switch for a *different* entity underneath a
// tile. This custom feature does exactly that: the tile keeps showing its
// own entity (e.g. a motion or door sensor and its state), and the feature
// row underneath toggles some other on/off entity — typically an
// `input_boolean` helper that an automation checks to decide whether it
// should listen to that sensor when arming the alarm.
//
// It renders the same `ha-control-switch` the native toggle feature uses,
// with the same power icon, so it is visually indistinguishable from the
// toggle on an automation tile.
//
// The one difference is the "on" color. The native feature paints itself
// with the tile's own state color, which for a sensor sitting at "Clear"
// is the inactive grey — a switch that stays grey while it is on. So this
// feature uses the theme's active color by default and takes an explicit
// `color` instead.
//
// It works with anything `homeassistant.toggle` accepts: input_boolean,
// switch, automation, light, ...
//
// Usage inside any tile card:
//   type: tile
//   entity: binary_sensor.hall_motion
//   features:
//     - type: custom:annika-entity-toggle-feature
//       entity: input_boolean.hall_motion_armed
//       color: green      # optional, HA color name or any CSS color
//
// In the Annika cards this is wired through the shared `toggle` key, so you
// never write the feature by hand:
//   motion_sensors:
//     - entity: binary_sensor.hall_motion
//       name: Hall Sensor
//       toggle: input_boolean.hall_motion_armed
//     - entity: binary_sensor.patio_motion
//       toggle:
//         entity: input_boolean.patio_motion_armed
//         color: green
;(() => {
  const FEATURE = 'annika-entity-toggle-feature'

  // mdi:power — the icon the native toggle feature puts on the switch knob.
  const MDI_POWER =
    'M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 ' +
    '7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,' +
    '9.28 18.64,6.88 16.56,5.44M13,3H11V13H13'

  // Color names the HA themes define as `--<name>-color`.
  const THEME_COLORS = new Set([
    'primary', 'accent', 'disabled', 'state-active', 'state-inactive',
    'red', 'pink', 'purple', 'deep-purple', 'indigo', 'blue', 'light-blue', 'cyan', 'teal',
    'green', 'light-green', 'lime', 'yellow', 'amber', 'orange', 'deep-orange', 'brown',
    'light-grey', 'grey', 'dark-grey', 'blue-grey', 'black', 'white',
  ])

  // "green" -> "var(--green-color)"; "#ff0000" / "rgb(...)" pass through.
  // Unset falls back to the theme's active color (what an "on" tile uses),
  // never to the tile's current color, which is grey while the sensor is idle.
  function cssColor(color) {
    if (!color) return 'var(--state-active-color, var(--primary-color))'
    const name = String(color).trim().replace(/_/g, '-')
    return THEME_COLORS.has(name) ? `var(--${name}-color)` : String(color)
  }

  class AnnikaEntityToggleFeature extends HTMLElement {
    // Any tile entity can carry this feature — what it toggles is unrelated
    // to the tile's own entity.
    static isSupported() {
      return true
    }

    static getStubConfig() {
      return { type: `custom:${FEATURE}` }
    }

    setConfig(config) {
      if (!config || typeof config.entity !== 'string') {
        throw new Error(`${FEATURE}: "entity" is required (the entity the switch controls)`)
      }
      this._config = config
      this._onColor = cssColor(config.color)
      this._build()
      this._update()
    }

    set hass(hass) {
      this._hass = hass
      this._update()
    }

    get hass() {
      return this._hass
    }

    // Set by hui-card-features for the tile's own entity — not used here,
    // this feature is deliberately about a different entity.
    set stateObj(stateObj) {
      this._stateObj = stateObj
    }

    set context(context) {
      this._context = context
    }

    set color(color) {
      this._tileColor = color
    }

    _state() {
      return this._hass?.states?.[this._config?.entity]
    }

    _build() {
      if (this._switch) return

      this.innerHTML = `
        <style>
          .annika-toggle-feature {
            display: block;
            width: 100%;
            height: var(--feature-height, 42px);
          }
          .annika-toggle-feature ha-control-switch {
            height: 100%;
            width: 100%;
            --control-switch-on-color: ${this._onColor};
            --control-switch-off-color: var(--disabled-color);
            --control-switch-background-opacity: 0.2;
          }
          .annika-toggle-fallback {
            display: flex;
            align-items: center;
            width: 100%;
            height: 100%;
            padding: 0;
            border: none;
            border-radius: var(--feature-border-radius, 12px);
            background: color-mix(in srgb, var(--disabled-color) 20%, transparent);
            cursor: pointer;
            overflow: hidden;
            transition: background 180ms ease-in-out;
          }
          .annika-toggle-fallback[disabled] {
            cursor: default;
            opacity: 0.5;
          }
          .annika-toggle-fallback[aria-checked='true'] {
            background: color-mix(in srgb, ${this._onColor} 20%, transparent);
          }
          .annika-toggle-fallback .knob {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 50%;
            height: 100%;
            border-radius: inherit;
            color: var(--white-color, #fff);
            background: var(--disabled-color);
            transform: translateX(0);
            transition: transform 180ms ease-in-out, background 180ms ease-in-out;
          }
          .annika-toggle-fallback[aria-checked='true'] .knob {
            background: ${this._onColor};
            transform: translateX(100%);
          }
          .annika-toggle-fallback .knob svg {
            width: 20px;
            height: 20px;
            fill: currentColor;
          }
        </style>
      `

      const wrapper = document.createElement('div')
      wrapper.className = 'annika-toggle-feature'

      if (customElements.get('ha-control-switch')) {
        this._switch = this._createNativeSwitch()
      } else {
        this._switch = this._createFallbackSwitch()
        // The native element is lazily loaded by HA; swap it in if it shows up.
        customElements.whenDefined('ha-control-switch').then(() => {
          if (!this._switch || this._isNative()) return
          const native = this._createNativeSwitch()
          this._switch.replaceWith(native)
          this._switch = native
          this._update()
        })
      }

      wrapper.appendChild(this._switch)
      this.appendChild(wrapper)
    }

    _isNative() {
      return this._switch?.tagName?.toLowerCase() === 'ha-control-switch'
    }

    _createNativeSwitch() {
      const element = document.createElement('ha-control-switch')
      // Same knob icon the native toggle feature uses.
      element.pathOn = MDI_POWER
      element.pathOff = MDI_POWER
      element.setAttribute('aria-label', this._config.entity)
      element.addEventListener('change', (event) => {
        event.stopPropagation()
        this._toggle()
      })
      return element
    }

    _createFallbackSwitch() {
      const element = document.createElement('button')
      element.type = 'button'
      element.className = 'annika-toggle-fallback'
      element.setAttribute('role', 'switch')
      element.setAttribute('aria-label', this._config.entity)

      const knob = document.createElement('div')
      knob.className = 'knob'
      knob.innerHTML = `<svg viewBox="0 0 24 24"><path d="${MDI_POWER}"></path></svg>`
      element.appendChild(knob)

      element.addEventListener('click', (event) => {
        event.stopPropagation()
        this._toggle()
      })
      return element
    }

    _update() {
      if (!this._switch || !this._config) return

      const stateObj = this._state()
      const isOn = stateObj?.state === 'on'
      const unavailable = !stateObj || stateObj.state === 'unavailable' || stateObj.state === 'unknown'

      if (this._isNative()) {
        this._switch.checked = isOn
        this._switch.disabled = unavailable
      } else {
        this._switch.setAttribute('aria-checked', String(isOn))
        this._switch.disabled = unavailable
        if (unavailable) this._switch.setAttribute('disabled', '')
        else this._switch.removeAttribute('disabled')
      }
    }

    _toggle() {
      const stateObj = this._state()
      if (!this._hass || !stateObj) return
      this._hass.callService('homeassistant', 'toggle', { entity_id: this._config.entity })
    }
  }

  if (!customElements.get(FEATURE)) {
    customElements.define(FEATURE, AnnikaEntityToggleFeature)
  }

  // HA renamed "tile features" to "card features"; register in both
  // registries so the feature is recognized on old and new frontends.
  const entry = {
    type: FEATURE,
    name: 'Annika Entity Toggle',
    supported: () => true,
    configurable: false,
  }
  for (const registry of ['customCardFeatures', 'customTileFeatures']) {
    window[registry] = window[registry] || []
    if (!window[registry].some((item) => item.type === FEATURE)) {
      window[registry].push(entry)
    }
  }
})()
