// Annika heating card.
//
// Renders a list of climate/thermostat entities as annika-ac-card instances
// (heading + tile with auto-detected features), arranged in a grid, 3 per
// row by default. Each ac-card instance figures out on its own which
// features that specific thermostat supports — this card only handles the
// layout.
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// Usage in a dashboard view:
//   type: custom:annika-heating-card
//   columns: 3
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   entities:
//     - entity: climate.playroom_thermostat
//       name: Playroom
//       icon: mdi:nintendo-game-boy
//       color: orange
//     - climate.office_thermostat
;(() => {
  const CARD = 'annika-heating-card'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  class AnnikaHeatingCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.entities) || config.entities.length === 0) {
        throw new Error(`${CARD}: "entities" must be a non-empty list of climate entities`)
      }
      this._config = config
      this._entities = annika().normalizeItems(config.entities, CARD)
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
      return Math.ceil((this._entities?.length || 0) / columns) * 3
    }

    getGridOptions() {
      return {
        columns: 'full',
      }
    }

    getLayoutOptions() {
      return {
        grid_columns: 'full',
      }
    }

    async _render() {
      if (!this._hass || !this._config || this._grid) return

      const { gridConfig, createHeader } = annika()
      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement(
        gridConfig(
          this._entities.map((item) => ({ type: 'custom:annika-ac-card', ...item })),
          this._config.columns || 3,
        ),
      )
      this._grid.hass = this._hass

      this.innerHTML = ''
      if (this._config.title) {
        this.appendChild(createHeader(this._config.title, '0 0 8px 4px'))
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
