// Annika AC (climate) card.
//
// Renders a single climate entity as a header (icon + name) plus a native
// HA tile card, with only the features the entity actually supports —
// not every AC has fan modes, swing, or horizontal swing, so each feature
// is gated on the entity's own `supported_features` bitmask / mode lists
// instead of being hardcoded.
//
// The config uses the shared Annika entity shape (see annika-common.js):
// `entity` is required, `name`, `icon` and `color` are optional.
//
// Usage in a dashboard section:
//   type: custom:annika-ac-card
//   entity: climate.main_bedroom
//   name: Main Bedroom AC
//   icon: mdi:bed-double
//   color: blue
;(() => {
  const CARD = 'annika-ac-card'

  // homeassistant.components.climate.const.ClimateEntityFeature
  const SUPPORT_TARGET_TEMPERATURE = 1
  const SUPPORT_TARGET_TEMPERATURE_RANGE = 2
  const SUPPORT_FAN_MODE = 8
  const SUPPORT_SWING_MODE = 32
  const SUPPORT_SWING_HORIZONTAL_MODE = 512

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  function featuresFor(stateObj) {
    const supported = stateObj?.attributes?.supported_features || 0
    const features = []

    if (supported & SUPPORT_TARGET_TEMPERATURE || supported & SUPPORT_TARGET_TEMPERATURE_RANGE) {
      features.push({ type: 'target-temperature' })
    }
    if ((stateObj?.attributes?.hvac_modes || []).length > 1) {
      features.push({ type: 'climate-hvac-modes' })
    }
    if (supported & SUPPORT_FAN_MODE) {
      features.push({ style: 'icons', type: 'climate-fan-modes' })
    }
    if (supported & SUPPORT_SWING_MODE) {
      features.push({ style: 'icons', type: 'climate-swing-modes' })
    }
    if (supported & SUPPORT_SWING_HORIZONTAL_MODE) {
      features.push({ style: 'icons', type: 'climate-swing-horizontal-modes' })
    }

    return features
  }

  class AnnikaAcCard extends HTMLElement {
    setConfig(config) {
      if (!config.entity) {
        throw new Error(`${CARD}: "entity" is required`)
      }
      this._config = config
      this._item = annika().normalizeItem(config, CARD)
      this._built = false
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._tile) {
        this._tile.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      return 3
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { tileConfig, displayName } = annika()
      const stateObj = this._hass.states[this._item.entity]
      const helpers = await window.loadCardHelpers()

      this.innerHTML = `
        <style>
          .annika-ac-header {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 1em;
            font-weight: 500;
            color: var(--secondary-text-color);
            margin: 0 0 8px 4px;
          }
        </style>
      `

      const header = document.createElement('div')
      header.className = 'annika-ac-header'
      if (this._item.icon) {
        const icon = document.createElement('ha-icon')
        icon.setAttribute('icon', this._item.icon)
        header.appendChild(icon)
      }
      const label = document.createElement('span')
      label.textContent = displayName(this._hass, this._item)
      header.appendChild(label)
      this.appendChild(header)

      // The name and icon are already in the header above, so the tile only
      // keeps the entity's color and its auto-detected features.
      this._tile = await helpers.createCardElement(
        tileConfig({ entity: this._item.entity, color: this._item.color }, { features: featuresFor(stateObj) }),
      )
      this._tile.hass = this._hass
      this.appendChild(this._tile)
    }
  }

  customElements.define('annika-ac-card', AnnikaAcCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-ac-card',
    name: 'Annika AC',
    description: 'Climate tile with auto-detected features based on what the entity actually supports.',
  })
})()
