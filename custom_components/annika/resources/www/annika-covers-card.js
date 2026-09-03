// Annika covers card.
//
// Renders covers (shutters, awnings, blinds, curtains, garage doors) as
// native HA tile cards, grouped under an area header. Tiles are laid out in
// a responsive, wrapping row (auto-fill grid): a fixed/consistent tile
// width, as many per row as fit the available width, wrapping to the next
// line instead of a fixed column count. Every tile gets exactly one feature
// so all tiles end up the same height — header (icon + name + state) plus a
// single row of controls underneath, no taller and no shorter regardless of
// how many buttons that feature has.
//
// By default the card takes no entity list at all: it reads Home
// Assistant's own registries and shows every `cover` in the house, grouped
// by their area and ordered by floor. A blind added to HA shows up here
// without touching the dashboard.
//
//   type: custom:annika-covers-card
//
// Auto mode only skips what HA already considers not user-facing (hidden,
// disabled, and config/diagnostic entities). Everything else is a knob:
//
//   type: custom:annika-covers-card
//   domains: [cover]             # what to pick up (default)
//   group_by: area               # area (default), category, label or none
//   color: primary               # tile color, applied to every tile (default)
//   groups: [living_room, Kitchen] # restrict *and* order; ids or names
//   exclude:                     # entity ids, or whole groups
//     - cover.garage_door
//     - garage
//   include:                     # force in something that was filtered out
//     - cover.service_shutter
//   overrides:                   # per-entity, same keys as the shared shape
//     cover.living_room_shutter:
//       name: Shutter
//       icon: mdi:window-shutter
//       color: amber
//   ungrouped: Other             # heading for the rest, or false to drop them
//   tile_min_width: 160          # px
//   heading_style: subtitle      # area headings: subtitle (default) or title
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//
// `groups` is the key every Annika card shares; here `areas` is the older
// name for it and still works, as does `unassigned` for `ungrouped`.
//
// Passing `groups` as a *map* instead of a list turns auto discovery off and
// pins the card to exactly what is listed, in that order — the original
// behaviour. Entities use the shared Annika shape (see annika-common.js):
// either a bare entity id or `{ entity, name?, icon?, color?, toggle? }`.
//
//   type: custom:annika-covers-card
//   groups:
//     Living Room:
//       - cover.living_room_shutter
//       - entity: cover.living_room_awning
//         name: Awning
//     Bedroom:
//       - cover.bedroom_blind
//
// The feature shown on each tile is derived from the entity's own
// supported_features bitmask:
//   - open/close/stop supported      -> cover-open-close feature (buttons)
//   - else tilt open/close/stop      -> cover-tilt feature (buttons)
// Only one of the two is picked (never both) so no tile grows a second
// feature row.
;(() => {
  const CARD = 'annika-covers-card'

  // homeassistant.components.cover.const.CoverEntityFeature
  const SUPPORT_OPEN = 1
  const SUPPORT_CLOSE = 2
  const SUPPORT_STOP = 8
  const SUPPORT_OPEN_TILT = 16
  const SUPPORT_CLOSE_TILT = 32
  const SUPPORT_STOP_TILT = 64

  const DEFAULT_TILE_MIN_WIDTH = 160
  const DEFAULT_DOMAINS = ['cover']
  // Same reasoning as the lights card: one uniform surface reads better than
  // a mix of per-state colors.
  const DEFAULT_COLOR = 'primary'
  // Area headings on a stock dashboard are subtitles, not titles.
  const DEFAULT_HEADING_STYLE = 'subtitle'
  const DEFAULT_GROUP_BY = 'area'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  function featuresFor(hass, entityId) {
    const stateObj = hass.states[entityId]
    const supported = stateObj?.attributes?.supported_features || 0

    if (supported & (SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP)) {
      return [{ type: 'cover-open-close' }]
    }
    if (supported & (SUPPORT_OPEN_TILT | SUPPORT_CLOSE_TILT | SUPPORT_STOP_TILT)) {
      return [{ type: 'cover-tilt' }]
    }

    return []
  }

  class AnnikaCoversCard extends HTMLElement {
    setConfig(config) {
      // `groups` is the shared key across every Annika card; `areas` is the
      // older name for it here and still works.
      const key = config.groups !== undefined ? 'groups' : 'areas'
      const given = config.groups !== undefined ? config.groups : config.areas
      const isManual = given && typeof given === 'object' && !Array.isArray(given)
      if (given !== undefined && !isManual && !Array.isArray(given)) {
        throw new Error(`${CARD}: "${key}" must be a list of group ids/names, or a map of heading to entities`)
      }

      this._config = config
      this._manualGroups = isManual
        ? Object.entries(given).map(([group, items]) => ({
            name: group,
            items: annika().normalizeItems(items, CARD, `${key}.${group}`),
          }))
        : undefined
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
      // when they change — that is what makes a newly added cover appear.
      // Registry objects keep their identity between state updates, so this
      // costs one reference check per update, not a rescan.
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
        // `areas` is the older name for this key and still works.
        groups: this._config.groups || this._config.areas,
        include: this._config.include,
        exclude: this._config.exclude,
        overrides: this._config.overrides,
        ungrouped: this._config.ungrouped ?? this._config.unassigned,
        categoryScope: this._config.category_scope,
      })
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { tileConfig, HEADING_CSS, appendHeading } = annika()
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
            /* The same spacing tokens a sections view uses between its own
               cards, so the rhythm matches a hand-built dashboard. */
            column-gap: var(--ha-section-column-gap, 8px);
            row-gap: var(--ha-section-row-gap, 8px);
          }
          .annika-tile-row > * {
            min-width: 0;
          }
          ${HEADING_CSS}
        </style>
      `
      this._cards = []

      const build = async (config) => {
        const element = await helpers.createCardElement(config)
        element.hass = this._hass
        this._cards.push(element)
        return element
      }

      for (const group of this._groups) {
        this._cards.push(
          await appendHeading(this, helpers, this._hass, group.name, {
            style: headingStyle,
            icon: group.icon,
          }),
        )

        const row = document.createElement('div')
        row.className = 'annika-tile-row'

        for (const item of group.items) {
          // The card-level color is a default: an item's own `color`, from
          // `overrides` or from a manual list, still wins.
          const tile = await build(
            tileConfig({ color, ...item }, { features: featuresFor(this._hass, item.entity) }),
          )
          row.appendChild(tile)
        }

        this.appendChild(row)
      }
    }
  }

    // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push(['annika-covers-card', AnnikaCoversCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-covers-card',
    name: 'Annika Covers',
    description:
      'Every cover in the house, discovered from the registries and grouped by area, as native tile cards with open/close/tilt features.',
  })
})()
