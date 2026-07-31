// Annika lights card.
//
// Renders a map of area name -> list of entity ids (lights, fans, dimmers,
// switches) as native HA tile cards, grouped under an area header, arranged
// in a 2-column grid per area. The feature shown on each tile is derived
// from the entity's own domain/capabilities:
//   - light with a dimmable color mode -> light-brightness feature
//   - light with only "onoff" support  -> toggle feature
//   - fan reporting a speed percentage -> fan-speed feature
//   - fan without speed support        -> toggle feature
//   - anything else (switch, etc.)     -> toggle feature
//
// Usage in a dashboard view:
//   type: custom:annika-lights-card
//   areas:
//     Living Room:
//       - light.living_room_main
//       - light.living_room_dimmer
//       - fan.living_room_ceiling
//     Kitchen:
//       - switch.kitchen_lights
;(() => {
  function featuresFor(hass, entityId) {
    const domain = entityId.split('.')[0]
    const stateObj = hass.states[entityId]

    if (domain === 'light') {
      const modes = stateObj?.attributes?.supported_color_modes || []
      if (modes.some((mode) => mode !== 'onoff')) {
        return [{ type: 'light-brightness' }]
      }
      return [{ type: 'toggle' }]
    }

    if (domain === 'fan') {
      if (stateObj?.attributes?.percentage != null) {
        return [{ type: 'fan-speed' }]
      }
      return [{ type: 'toggle' }]
    }

    return [{ type: 'toggle' }]
  }

  class AnnikaLightsCard extends HTMLElement {
    setConfig(config) {
      if (!config.areas || typeof config.areas !== 'object' || Array.isArray(config.areas)) {
        throw new Error('annika-lights-card: "areas" must be a map of area name to a list of entity ids')
      }
      this._config = config
      this._built = false
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._grids) {
        for (const grid of this._grids) grid.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const areas = Object.values(this._config?.areas || {})
      const tileRows = areas.reduce((sum, list) => sum + Math.ceil(list.length / 2), 0)
      return tileRows * 2 + areas.length
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const helpers = await window.loadCardHelpers()
      this.innerHTML = ''
      this._grids = []

      for (const [area, entityIds] of Object.entries(this._config.areas)) {
        const header = document.createElement('div')
        header.textContent = area
        header.style.fontSize = '1.2em'
        header.style.fontWeight = '500'
        header.style.margin = '16px 0 8px 4px'
        this.appendChild(header)

        const grid = await helpers.createCardElement({
          type: 'grid',
          columns: 2,
          square: false,
          cards: entityIds.map((entityId) => ({
            type: 'tile',
            entity: entityId,
            features: featuresFor(this._hass, entityId),
            features_position: 'bottom',
          })),
        })
        grid.hass = this._hass
        this._grids.push(grid)
        this.appendChild(grid)
      }
    }
  }

  customElements.define('annika-lights-card', AnnikaLightsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-lights-card',
    name: 'Annika Lights',
    description: 'Lists lights/fans/switches grouped by area as native tile cards with area-appropriate features.',
  })
})()
