// Annika automations card.
//
// Lists a fixed set of automations as native HA tile cards (toggle feature),
// arranged in a 2-column grid. The list is always given explicitly — unlike
// the lights and covers cards, this one does not discover anything on its
// own: automations rarely carry an area, and which of them belong on a
// dashboard is a judgement call, not something the registry knows.
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// Flat, no headings:
//   type: custom:annika-automations-card
//   title: Automations   # optional header above everything
//   columns: 2           # optional, tiles per row (default 2)
//   color: primary       # optional, tile color for every tile (default);
//                        # use `state` for Home Assistant's state coloring
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   entities:
//     - automation.front_door_alert
//     - entity: automation.night_lights
//       name: Night Lights
//       icon: mdi:weather-night
//
// Grouped under headings — pass `groups` as a map of heading to entities,
// same shape as the lights/covers cards take their areas. Groups render in
// the order they are written:
//   type: custom:annika-automations-card
//   groups:
//     Alarm:
//       - automation.alarm_night
//       - entity: automation.alarm_away
//         name: Alarm Away
//     Lights:
//       - automation.night_lights
//     Notifications:
//       - automation.doorbell_push
;(() => {
  const CARD = 'annika-automations-card'
  const DEFAULT_COLUMNS = 2
  // Same reasoning as the lights and covers cards: one uniform surface reads
  // better than a mix of per-state colors.
  const DEFAULT_COLOR = 'primary'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  class AnnikaAutomationsCard extends HTMLElement {
    setConfig(config) {
      const { normalizeItems } = annika()

      if (config.groups !== undefined) {
        if (typeof config.groups !== 'object' || Array.isArray(config.groups)) {
          throw new Error(`${CARD}: "groups" must be a map of heading to a list of automations`)
        }
        this._groups = Object.entries(config.groups).map(([name, items]) => ({
          name,
          items: normalizeItems(items, CARD, `groups.${name}`),
        }))
      } else {
        if (!Array.isArray(config.entities) || config.entities.length === 0) {
          throw new Error(`${CARD}: "entities" must be a non-empty list of automations, or use "groups"`)
        }
        // A single unnamed group renders exactly like the flat list did.
        this._groups = [{ name: undefined, items: normalizeItems(config.entities, CARD) }]
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
      const columns = this._config?.columns || DEFAULT_COLUMNS
      return this._groups.reduce(
        (size, group) => size + Math.ceil(group.items.length / columns) * 2 + (group.name ? 1 : 0),
        0,
      )
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
      const columns = this._config.columns || DEFAULT_COLUMNS
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color

      this.innerHTML = ''
      if (this._config.title) {
        this.appendChild(createHeader(this._config.title, '0 0 8px 4px'))
      }

      this._grids = []
      for (const [index, group] of this._groups.entries()) {
        if (group.name) {
          // No top margin on the first heading when it is the first thing in
          // the card, so grouped and ungrouped cards start at the same place.
          const first = index === 0 && !this._config.title
          this.appendChild(createHeader(group.name, first ? '0 0 8px 4px' : '16px 0 8px 4px'))
        }

        const grid = await helpers.createCardElement(
          gridConfig(
            // The card-level color is a default: an entity's own `color`
            // still wins.
            group.items.map((item) => tileConfig({ color, ...item }, { features: [{ type: 'toggle' }] })),
            columns,
          ),
        )
        grid.hass = this._hass
        this._grids.push(grid)
        this.appendChild(grid)
      }
    }
  }

  customElements.define('annika-automations-card', AnnikaAutomationsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-automations-card',
    name: 'Annika Automations',
    description: 'Lists a given set of automations as native tile cards with a toggle feature, optionally grouped under headings.',
  })
})()
