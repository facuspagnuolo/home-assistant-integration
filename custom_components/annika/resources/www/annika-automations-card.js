// Annika automations card.
//
// Renders automations as native HA tile cards with a toggle feature, laid
// out in a responsive, wrapping row (auto-fill grid): a fixed/consistent
// tile width, as many per row as fit the available width, wrapping to the
// next line instead of a fixed column count — the same layout the lights and
// covers cards use.
//
// By default the card takes no entity list at all: it reads Home Assistant's
// own registries and shows every automation in the house, grouped by the
// categories you already use in Settings > Automations. An automation added
// to HA shows up here without touching the dashboard.
//
//   type: custom:annika-automations-card
//
// Automations rarely carry an area, so this card groups by category instead
// of area — but the axis is a knob like everything else. If nothing is
// grouped (no categories set, older Home Assistant without the category
// registry), the card renders one plain list with no heading rather than a
// lone "Other".
//
//   type: custom:annika-automations-card
//   group_by: category           # category (default), label, area or none
//   title: Automations           # optional header above everything
//   tile_min_width: 160          # px
//   color: primary               # tile color for every tile (default);
//                                # use `state` for HA's state coloring
//   groups: [Alarm, Lights]      # restrict *and* order; ids or names
//   exclude:                     # entity ids, or whole groups
//     - automation.debug_helper
//     - Deprecated
//   include:                     # force in something that was filtered out
//     - automation.hidden_but_wanted
//   overrides:                   # per-entity, same keys as the shared shape
//     automation.alarm_night:
//       name: Alarm Night
//       icon: mdi:weather-night
//       color: amber
//   ungrouped: Other             # heading for the rest, or false to drop them
//   heading_style: subtitle      # group headings: subtitle (default) or title
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//
// Passing `groups` as a *map* instead of a list turns auto discovery off and
// pins the card to exactly what is listed, in that order:
//   type: custom:annika-automations-card
//   groups:
//     Alarm:
//       - automation.alarm_night
//       - entity: automation.alarm_away
//         name: Alarm Away
//     Lights:
//       - automation.night_lights
//
// `entities` is the same thing without headings — one flat list:
//   type: custom:annika-automations-card
//   entities:
//     - automation.front_door_alert
//     - entity: automation.night_lights
//       name: Night Lights
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
;(() => {
  const CARD = 'annika-automations-card'
  const DEFAULT_TILE_MIN_WIDTH = 160
  const DEFAULT_DOMAINS = ['automation']
  // Same reasoning as the lights and covers cards: one uniform surface reads
  // better than a mix of per-state colors.
  const DEFAULT_COLOR = 'primary'
  // Group headings on a stock dashboard are subtitles, not titles.
  const DEFAULT_HEADING_STYLE = 'subtitle'
  // Areas are for things in rooms; automations live in categories.
  const DEFAULT_GROUP_BY = 'category'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  class AnnikaAutomationsCard extends HTMLElement {
    setConfig(config) {
      const { normalizeItems } = annika()

      if (config.groups !== undefined && typeof config.groups !== 'object') {
        throw new Error(`${CARD}: "groups" must be a list of group ids/names, or a map of heading to automations`)
      }

      this._config = config
      if (Array.isArray(config.entities)) {
        if (config.entities.length === 0) {
          throw new Error(`${CARD}: "entities" must be a non-empty list of automations`)
        }
        // A single unnamed group renders as a plain list, no heading.
        this._manualGroups = [{ name: undefined, items: normalizeItems(config.entities, CARD) }]
      } else if (config.groups && !Array.isArray(config.groups)) {
        this._manualGroups = Object.entries(config.groups).map(([group, items]) => ({
          name: group,
          items: normalizeItems(items, CARD, `groups.${group}`),
        }))
      } else {
        this._manualGroups = undefined
      }

      this._reset()
      this._render()
    }

    _reset() {
      this._built = false
      this._cards = undefined
      this._groups = undefined
    }

    set hass(hass) {
      const previous = this._hass
      this._hass = hass

      // Auto mode is a snapshot of the registries, so it has to be rebuilt
      // when they change — that is what makes a newly added automation
      // appear, or one that was just given a category move into it. Registry
      // objects keep their identity between state updates, so this costs one
      // reference check per update, not a rescan.
      if (!this._manualGroups && previous && this._built) {
        const changed =
          previous.entities !== hass.entities ||
          previous.devices !== hass.devices ||
          previous.areas !== hass.areas ||
          previous.floors !== hass.floors
        if (changed) {
          this._reset()
          this._render()
          return
        }
      }

      if (this._cards) {
        for (const card of this._cards) card.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const groups = this._groups || this._manualGroups
      // Asked before the first render, auto mode has nothing to measure yet.
      if (!groups) return 6
      const total = groups.reduce((sum, group) => sum + group.items.length, 0)
      return Math.ceil(total / 4) * 2 + groups.length
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

    async _discover() {
      if (this._manualGroups) return this._manualGroups

      const { discoverEntities } = annika()
      return discoverEntities(this._hass, CARD, {
        domains: this._config.domains || DEFAULT_DOMAINS,
        groupBy: this._config.group_by || DEFAULT_GROUP_BY,
        groups: Array.isArray(this._config.groups) ? this._config.groups : undefined,
        include: this._config.include,
        exclude: this._config.exclude,
        overrides: this._config.overrides,
        ungrouped: this._config.ungrouped,
        categoryScope: this._config.category_scope,
      })
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { tileConfig, headingConfig } = annika()
      const helpers = await window.loadCardHelpers()
      const minWidth = this._config.tile_min_width || DEFAULT_TILE_MIN_WIDTH
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color
      const headingStyle = this._config.heading_style || DEFAULT_HEADING_STYLE

      this._groups = await this._discover()

      this.innerHTML = `
        <style>
          .annika-tile-row {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(${minWidth}px, 1fr));
            column-gap: var(--ha-section-column-gap, 8px);
            row-gap: var(--ha-section-row-gap, 8px);
          }
          .annika-tile-row > * {
            min-width: 0;
          }
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

      const appendHeading = async (text, style, icon) => {
        const heading = await build(headingConfig(text, { style, icon }))
        heading.classList.add('annika-heading')
        this.appendChild(heading)
      }

      if (this._config.title) await appendHeading(this._config.title, 'title')

      for (const group of this._groups) {
        if (group.name) await appendHeading(group.name, headingStyle, group.icon)

        const row = document.createElement('div')
        row.className = 'annika-tile-row'

        for (const item of group.items) {
          // The card-level color is a default: an entity's own `color` wins.
          row.appendChild(
            await build(tileConfig({ color, ...item }, { features: [{ type: 'toggle' }] })),
          )
        }

        this.appendChild(row)
      }
    }
  }

  customElements.define('annika-automations-card', AnnikaAutomationsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-automations-card',
    name: 'Annika Automations',
    description:
      'Every automation in the house, discovered from the registries and grouped by category, as native tile cards with a toggle feature.',
  })
})()
