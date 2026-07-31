// Annika heating card.
//
// Renders a list of climate/thermostat entities as annika-ac-card instances
// (heading + tile with auto-detected features), arranged in a grid, 3 per
// row by default. Each ac-card instance figures out on its own which
// features that specific thermostat supports — this card only handles the
// layout.
//
// Usage in a dashboard view:
//   type: custom:annika-heating-card
//   columns: 3
//   entities:
//     - entity: climate.playroom_thermostat
//       name: Playroom
//       icon: mdi:nintendo-game-boy
//       color: orange
//     - entity: climate.office_thermostat
//       name: Office
;(() => {
  class AnnikaHeatingCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.entities) || config.entities.length === 0) {
        throw new Error('annika-heating-card: "entities" must be a non-empty list of { entity, name?, icon?, color? }')
      }
      this._config = config
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._grid) {
        this._grid.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const columns = this._config?.columns || 3
      return Math.ceil((this._config?.entities?.length || 0) / columns) * 3
    }

    async _render() {
      if (!this._hass || !this._config || this._grid) return

      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement({
        type: 'grid',
        columns: this._config.columns || 3,
        square: false,
        cards: this._config.entities.map((item) => ({
          type: 'custom:annika-ac-card',
          entity: item.entity,
          name: item.name,
          icon: item.icon,
          color: item.color,
        })),
      })
      this._grid.hass = this._hass

      this.innerHTML = ''
      if (this._config.title) {
        const header = document.createElement('div')
        header.textContent = this._config.title
        header.style.fontSize = '1.2em'
        header.style.fontWeight = '500'
        header.style.margin = '0 0 8px 4px'
        this.appendChild(header)
      }
      this.appendChild(this._grid)
    }
  }

  customElements.define('annika-heating-card', AnnikaHeatingCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-heating-card',
    name: 'Annika Heating',
    description: 'Lists thermostats as annika-ac-card tiles arranged in a grid (3 per row by default).',
  })
})()
