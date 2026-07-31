// Annika automations card.
//
// Lists a fixed set of automations as native HA tile cards (toggle feature),
// arranged in a 2-column grid. The list of automations to render is always
// given explicitly via `entities` in the card config — this card does not
// discover or filter entities on its own.
//
// Usage in a dashboard view:
//   type: custom:annika-automations-card
//   title: Automations
//   entities:
//     - automation.front_door_alert
//     - automation.night_lights
;(() => {
  class AnnikaAutomationsCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.entities) || config.entities.length === 0) {
        throw new Error('annika-automations-card: "entities" must be a non-empty list of automation entity ids')
      }
      this._config = config
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
      return Math.ceil((this._config?.entities?.length || 0) / 2) * 2
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement({
        type: 'grid',
        columns: 2,
        square: false,
        cards: this._config.entities.map((entityId) => ({
          type: 'tile',
          entity: entityId,
          features: [{ type: 'toggle' }],
          features_position: 'bottom',
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

  customElements.define('annika-automations-card', AnnikaAutomationsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-automations-card',
    name: 'Annika Automations',
    description: 'Lists a given set of automations as native tile cards with a toggle feature.',
  })
})()
