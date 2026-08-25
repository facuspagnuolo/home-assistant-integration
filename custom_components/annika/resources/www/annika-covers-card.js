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
//   color: primary               # tile color, applied to every tile (default)
//   areas: [living_room, Kitchen]  # restrict *and* order; ids or names
//   exclude:                     # entity ids, or whole areas
//     - cover.garage_door
//     - garage
//   include:                     # force in something that was filtered out
//     - cover.service_shutter
//   overrides:                   # per-entity, same keys as the shared shape
//     cover.living_room_shutter:
//       name: Shutter
//       icon: mdi:window-shutter
//       color: amber
//   unassigned: Other            # heading for entities with no area, or false
//   tile_min_width: 160          # px
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//
// Passing `areas` as a *map* instead of a list turns auto discovery off and
// pins the card to exactly what is listed, in that order — the original
// behaviour. Entities use the shared Annika shape (see annika-common.js):
// either a bare entity id or `{ entity, name?, icon?, color?, toggle? }`.
//
//   type: custom:annika-covers-card
//   areas:
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
      const isManual = config.areas && typeof config.areas === 'object' && !Array.isArray(config.areas)
      if (config.areas !== undefined && !isManual && !Array.isArray(config.areas)) {
        throw new Error(`${CARD}: "areas" must be a list of area ids/names, or a map of area name to entities`)
      }

      this._config = config
      this._manualAreas = isManual
        ? Object.entries(config.areas).map(([area, items]) => ({
            name: area,
            items: annika().normalizeItems(items, CARD, `areas.${area}`),
          }))
        : undefined
      this._reset()
      this._render()
    }

    _reset() {
      this._built = false
      this._tiles = undefined
      this._groups = undefined
    }

    set hass(hass) {
      const previous = this._hass
      this._hass = hass

      // Auto mode is a snapshot of the registries, so it has to be rebuilt
      // when they change — that is what makes a newly added cover appear.
      // Registry objects keep their identity between state updates, so this
      // costs one reference check per update, not a rescan.
      if (!this._manualAreas && previous && this._built) {
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

      if (this._tiles) {
        for (const tile of this._tiles) tile.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const groups = this._groups || this._manualAreas
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

    _discover() {
      if (this._manualAreas) return this._manualAreas

      const { entitiesByArea } = annika()
      return entitiesByArea(this._hass, CARD, {
        domains: this._config.domains || DEFAULT_DOMAINS,
        areas: this._config.areas,
        include: this._config.include,
        exclude: this._config.exclude,
        overrides: this._config.overrides,
        unassigned: this._config.unassigned,
      })
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { tileConfig, createHeader } = annika()
      const helpers = await window.loadCardHelpers()
      const minWidth = this._config.tile_min_width || DEFAULT_TILE_MIN_WIDTH
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color

      this._groups = this._discover()

      this.innerHTML = `
        <style>
          .annika-tile-row {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(${minWidth}px, 1fr));
            gap: 8px;
          }
          .annika-tile-row > * {
            min-width: 0;
          }
        </style>
      `
      this._tiles = []

      for (const group of this._groups) {
        this.appendChild(createHeader(group.name))

        const row = document.createElement('div')
        row.className = 'annika-tile-row'

        for (const item of group.items) {
          const tile = await helpers.createCardElement(
            // The card-level color is a default: an item's own `color`, from
            // `overrides` or from a manual list, still wins.
            tileConfig({ color, ...item }, { features: featuresFor(this._hass, item.entity) }),
          )
          tile.hass = this._hass
          this._tiles.push(tile)
          row.appendChild(tile)
        }

        this.appendChild(row)
      }
    }
  }

  customElements.define('annika-covers-card', AnnikaCoversCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-covers-card',
    name: 'Annika Covers',
    description:
      'Every cover in the house, discovered from the registries and grouped by area, as native tile cards with open/close/tilt features.',
  })
})()
