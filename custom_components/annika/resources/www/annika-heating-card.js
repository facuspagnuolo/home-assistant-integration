// Annika heating card.
//
// A name for annika-ac-card, nothing more: a thermostat and an air
// conditioner are both `climate` entities, and what tells them apart on a
// dashboard is which entities you list, not how they are drawn. This card
// forwards everything to annika-ac-card, which renders a list of climate
// entities as a heading and a tile each, in a grid 3 per row — see
// annika-ac-card.js for the whole config.
//
// Kept because dashboards already say `custom:annika-heating-card`, and
// because "heating" is the honest name for that half of a house.
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
    // Built here and nowhere else. `hass` can arrive before `setConfig` —
    // and, being a setter, even during construction — so building the inner
    // card from there would touch the DOM before this element is ready.
    setConfig(config) {
      if (!Array.isArray(config.entities) || config.entities.length === 0) {
        throw new Error(`${CARD}: "entities" must be a non-empty list of climate entities`)
      }

      if (!this._card) {
        const AcCard = customElements.get('annika-ac-card')
        if (!AcCard) throw new Error(`${CARD}: annika-ac-card.js is not loaded`)
        this._card = new AcCard()
        this.innerHTML = ''
        this.appendChild(this._card)
      }

      this._card.setConfig(config)
      if (this._hass) this._card.hass = this._hass
    }

    set hass(hass) {
      this._hass = hass
      if (this._card) this._card.hass = hass
    }

    getCardSize() {
      return this._card ? this._card.getCardSize() : 3
    }

    getGridOptions() {
      return this._card ? this._card.getGridOptions() : { columns: 'full' }
    }

    getLayoutOptions() {
      return this._card ? this._card.getLayoutOptions() : { grid_columns: 'full' }
    }
  }

    // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push(['annika-heating-card', AnnikaHeatingCard, ['annika-ac-card']])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-heating-card',
    name: 'Annika Heating',
    description: 'Thermostats as a heading and a tile each, in a grid (3 per row by default). Same card as Annika AC.',
  })
})()
