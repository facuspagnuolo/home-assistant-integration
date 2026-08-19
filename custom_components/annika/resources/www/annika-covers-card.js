// Annika covers card.
//
// Renders a map of area name -> list of cover entities (shutters, awnings,
// blinds, garage doors, etc.) as native HA tile cards, grouped under an area
// header. Tiles are laid out in a responsive, wrapping row (auto-fill grid):
// a fixed/consistent tile width, as many per row as fit the available
// width, wrapping to the next line instead of a fixed column count. Every
// tile gets exactly one feature so all tiles end up the same height —
// header (icon + name + state) plus a single row of controls underneath,
// no taller and no shorter regardless of how many buttons that feature has.
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// The feature shown on each tile is derived from the entity's own
// supported_features bitmask:
//   - open/close/stop supported      -> cover-open-close feature (buttons)
//   - else tilt open/close/stop      -> cover-tilt feature (buttons)
// Only one of the two is picked (never both) so no tile grows a second
// feature row.
//
// Usage in a dashboard view:
//   type: custom:annika-covers-card
//   tile_min_width: 160  # optional, px
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   areas:
//     Living Room:
//       - cover.living_room_shutter
//       - entity: cover.living_room_awning
//         name: Awning
//         icon: mdi:awning-outline
//     Bedroom:
//       - cover.bedroom_blind
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
      if (!config.areas || typeof config.areas !== 'object' || Array.isArray(config.areas)) {
        throw new Error(`${CARD}: "areas" must be a map of area name to a list of entities`)
      }
      this._config = config
      this._areas = Object.fromEntries(
        Object.entries(config.areas).map(([area, items]) => [
          area,
          annika().normalizeItems(items, CARD, `areas.${area}`),
        ]),
      )
      this._built = false
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._tiles) {
        for (const tile of this._tiles) tile.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const areas = Object.values(this._areas || {})
      const totalEntities = areas.reduce((sum, list) => sum + list.length, 0)
      return Math.ceil(totalEntities / 4) * 2 + areas.length
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

      const { tileConfig, createHeader } = annika()
      const helpers = await window.loadCardHelpers()
      const minWidth = this._config.tile_min_width || DEFAULT_TILE_MIN_WIDTH

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

      for (const [area, items] of Object.entries(this._areas)) {
        this.appendChild(createHeader(area))

        const row = document.createElement('div')
        row.className = 'annika-tile-row'

        for (const item of items) {
          const tile = await helpers.createCardElement(
            tileConfig(item, { features: featuresFor(this._hass, item.entity) }),
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
    description: 'Lists covers (shutters, awnings, blinds) grouped by area as native tile cards in a responsive wrapping row with open/close/tilt button features.',
  })
})()
