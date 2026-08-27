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
//   heading_style: subtitle  # group headings: subtitle (default) or title
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
  // Group headings on a stock dashboard are subtitles, not titles.
  const DEFAULT_HEADING_STYLE = 'subtitle'

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
      if (this._cards) {
        for (const card of this._cards) card.hass = hass
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

      const { tileConfig, gridConfig, headingConfig } = annika()
      const helpers = await window.loadCardHelpers()
      const columns = this._config.columns || DEFAULT_COLUMNS
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color
      const headingStyle = this._config.heading_style || DEFAULT_HEADING_STYLE

      this.innerHTML = `
        <style>
          .annika-heading {
            display: block;
          }
          .annika-heading:not(:first-child) {
            margin-top: var(--ha-section-row-gap, 8px);
          }
        </style>
      `
      this._cards = []

      const build = async (config) => {
        const element = await helpers.createCardElement(config)
        element.hass = this._hass
        this._cards.push(element)
        return element
      }

      const appendHeading = async (text, style) => {
        const heading = await build(headingConfig(text, { style }))
        heading.classList.add('annika-heading')
        this.appendChild(heading)
      }

      if (this._config.title) await appendHeading(this._config.title, 'title')

      for (const group of this._groups) {
        if (group.name) await appendHeading(group.name, headingStyle)

        // The card-level color is a default: an entity's own `color` still wins.
        const grid = await build(
          gridConfig(
            group.items.map((item) => tileConfig({ color, ...item }, { features: [{ type: 'toggle' }] })),
            columns,
          ),
        )
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
