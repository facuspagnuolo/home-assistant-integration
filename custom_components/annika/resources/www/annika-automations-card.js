// Annika automations card.
//
// Lists a fixed set of automations as native HA tile cards (toggle feature),
// arranged in a 2-column grid. The list of automations to render is always
// given explicitly via `entities` in the card config — this card does not
// discover or filter entities on its own.
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// Usage in a dashboard view:
//   type: custom:annika-automations-card
//   title: Automations
//   columns: 2           # optional, tiles per row (default 2)
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   entities:
//     - automation.front_door_alert
//     - entity: automation.night_lights
//       name: Night Lights
//       icon: mdi:weather-night
;(() => {
  const CARD = 'annika-automations-card'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  class AnnikaAutomationsCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.entities) || config.entities.length === 0) {
        throw new Error(`${CARD}: "entities" must be a non-empty list of automations`)
      }
      this._config = config
      this._entities = annika().normalizeItems(config.entities, CARD)
      this._built = false
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
      return Math.ceil((this._entities?.length || 0) / (this._config?.columns || 2)) * 2
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
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { tileConfig, gridConfig, createHeader } = annika()
      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement(
        gridConfig(
          this._entities.map((item) => tileConfig(item, { features: [{ type: 'toggle' }] })),
          this._config.columns || 2,
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

  customElements.define('annika-automations-card', AnnikaAutomationsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-automations-card',
    name: 'Annika Automations',
    description: 'Lists a given set of automations as native tile cards with a toggle feature.',
  })
})()
