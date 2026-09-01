// Annika "entity toggle" tile feature.
//
// A native tile feature can only act on the tile's own entity, so there is
// no built-in way to show a control for a *different* entity underneath a
// tile. This custom feature does exactly that: the tile keeps showing its
// own entity (e.g. a motion or door sensor and its state), and the row
// underneath toggles some other on/off entity — typically the participation
// switch Annika creates for that sensor, deciding whether it takes part in
// the alarm.
//
// Three looks:
//
//   inline    (default) a small square pulled up into the tile's own row, so
//             the tile stays one row tall. A feature normally gets a row of
//             its own, which makes every sensor tile twice as tall for a
//             checkbox. This collapses that row to nothing and positions the
//             box over it. It is the one place here that leans on the tile's
//             geometry rather than on config, so if a Home Assistant release
//             ever moves things around, fall back to `checkbox`.
//   inline-switch  the very same `ha-control-switch` the native toggle
//             feature renders, but in the tile's own row. Same control, one
//             row instead of two — the native feature always takes a row of
//             its own and that is not configurable.
//   checkbox  the same square, on its own row. Taller, but nothing about the
//             tile's internals is assumed.
//   switch    the same `ha-control-switch` the native toggle feature uses,
//             for when the toggle *is* the point of the tile.
//
// The "on" color is deliberately not the tile's state color: the native
// feature paints itself with it, and for a sensor sitting at "Clear" that is
// the inactive grey — a control that stays grey while it is on. This one
// defaults to `primary`, the same default every Annika card uses for its
// tiles, and takes an explicit `color`.
//
// It works with anything `homeassistant.toggle` accepts: input_boolean,
// switch, automation, light, ...
//
// Usage inside any tile card:
//   type: tile
//   entity: binary_sensor.hall_motion
//   features:
//     - type: custom:annika-entity-toggle-feature
//       entity: switch.hall_motion_sensor_alarm_enabled
//       style: inline     # optional, the default
//       color: primary    # optional, HA color name or any CSS color
//
// In the Annika alarm card this is wired through the shared `toggle` key, or
// found automatically from the Annika switch that names this sensor as its
// source — see annika-alarm-card.js.
;(() => {
  const FEATURE = 'annika-entity-toggle-feature'
  const STYLES = ['inline', 'inline-switch', 'checkbox', 'switch']

  // mdi:power — the icon the native toggle feature puts on the switch knob.
  const MDI_POWER =
    'M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 ' +
    '7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,' +
    '9.28 18.64,6.88 16.56,5.44M13,3H11V13H13'
  // mdi:check
  const MDI_CHECK = 'M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z'

  // Color names the HA themes define as `--<name>-color`.
  const THEME_COLORS = new Set([
    'primary', 'accent', 'disabled', 'state-active', 'state-inactive',
    'red', 'pink', 'purple', 'deep-purple', 'indigo', 'blue', 'light-blue', 'cyan', 'teal',
    'green', 'light-green', 'lime', 'yellow', 'amber', 'orange', 'deep-orange', 'brown',
    'light-grey', 'grey', 'dark-grey', 'blue-grey', 'black', 'white',
  ])

  function icon(path) {
    return `<svg viewBox="0 0 24 24"><path d="${path}"></path></svg>`
  }

  // "green" -> "var(--green-color)"; "#ff0000" / "rgb(...)" pass through.
  function cssColor(color) {
    if (!color) return 'var(--primary-color)'
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
        throw new Error(`${FEATURE}: "entity" is required (the entity the control toggles)`)
      }
      const style = config.style || 'inline'
      if (!STYLES.includes(style)) {
        throw new Error(`${FEATURE}: "style" must be one of ${STYLES.join(', ')}`)
      }
      this._config = config
      this._style = style
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
      if (this._control) return

      this.innerHTML = `
        <style>
          .annika-toggle-feature {
            display: flex;
            align-items: center;
            width: 100%;
            /* Same row height as any other feature, so tiles with and without
               one still line up. Only the control inside is smaller. */
            height: var(--feature-height, 42px);
          }
          .annika-toggle-feature.checkbox {
            justify-content: flex-end;
          }
          /* The row collapses to nothing and the box is placed over the tile's
             own row, which sits directly above it. */
          .annika-toggle-feature.inline {
            height: 0;
            position: relative;
            justify-content: flex-end;
            overflow: visible;
          }
          .annika-toggle-feature.inline-switch {
            height: 0;
            position: relative;
            justify-content: flex-end;
            overflow: visible;
          }
          .annika-toggle-feature.inline-switch ha-control-switch,
          .annika-toggle-feature.inline-switch .annika-toggle-fallback {
            position: absolute;
            right: 0;
            bottom: 4px;
            width: 45%;
            height: 34px;
          }
          .annika-toggle-feature.inline .annika-toggle-checkbox {
            position: absolute;
            right: 0;
            /* Measured against the tile's row, which ends just above this
               collapsed one — enough to sit level with the icon and the name
               rather than hanging off the bottom. */
            bottom: 9px;
          }
          .annika-toggle-checkbox {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            padding: 0;
            border: 2px solid var(--disabled-color);
            border-radius: 6px;
            background: transparent;
            color: transparent;
            cursor: pointer;
            transition: background 150ms ease-in-out, border-color 150ms ease-in-out,
              color 150ms ease-in-out;
          }
          .annika-toggle-checkbox[aria-checked='true'] {
            background: ${this._onColor};
            border-color: ${this._onColor};
            color: var(--white-color, #fff);
          }
          .annika-toggle-checkbox[disabled] {
            cursor: default;
            opacity: 0.4;
          }
          .annika-toggle-checkbox svg {
            width: 15px;
            height: 15px;
            fill: currentColor;
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
      wrapper.className = `annika-toggle-feature ${this._style}`

      if (this._style === 'checkbox' || this._style === 'inline') {
        // Drawn here rather than borrowed from Home Assistant: nothing native
        // is this small, and it keeps the default look free of any dependency
        // on HA's internal elements.
        this._control = this._createCheckbox()
      } else if (customElements.get('ha-control-switch')) {
        this._control = this._createNativeSwitch()
      } else {
        this._control = this._createFallbackSwitch()
        // The native element is lazily loaded by HA; swap it in if it shows up.
        customElements.whenDefined('ha-control-switch').then(() => {
          if (!this._control || this._isNative()) return
          const native = this._createNativeSwitch()
          this._control.replaceWith(native)
          this._control = native
          this._update()
        })
      }

      wrapper.appendChild(this._control)
      this.appendChild(wrapper)
    }

    _isNative() {
      return this._control?.tagName?.toLowerCase() === 'ha-control-switch'
    }

    _button(className, iconPath) {
      const element = document.createElement('button')
      element.type = 'button'
      element.className = className
      element.setAttribute('role', 'switch')
      element.setAttribute('aria-label', this._config.entity)
      if (iconPath) element.innerHTML = icon(iconPath)
      element.addEventListener('click', (event) => {
        event.stopPropagation()
        this._toggle()
      })
      return element
    }

    _createCheckbox() {
      return this._button('annika-toggle-checkbox', MDI_CHECK)
    }

    _createFallbackSwitch() {
      // The fallback's icon lives on the sliding knob, not on the button.
      const element = this._button('annika-toggle-fallback')
      const knob = document.createElement('div')
      knob.className = 'knob'
      knob.innerHTML = icon(MDI_POWER)
      element.appendChild(knob)
      return element
    }

    _createNativeSwitch() {
      const element = document.createElement('ha-control-switch')
      element.pathOn = MDI_POWER
      element.pathOff = MDI_POWER
      element.setAttribute('aria-label', this._config.entity)
      element.addEventListener('change', (event) => {
        event.stopPropagation()
        this._toggle()
      })
      return element
    }

    _update() {
      if (!this._control || !this._config) return

      const stateObj = this._state()
      const isOn = stateObj?.state === 'on'
      const unavailable = !stateObj || stateObj.state === 'unavailable' || stateObj.state === 'unknown'

      if (this._isNative()) {
        this._control.checked = isOn
        this._control.disabled = unavailable
        return
      }

      this._control.setAttribute('aria-checked', String(isOn))
      this._control.disabled = unavailable
      if (unavailable) this._control.setAttribute('disabled', '')
      else this._control.removeAttribute('disabled')
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
