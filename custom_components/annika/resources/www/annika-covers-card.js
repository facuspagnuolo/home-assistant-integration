// Annika covers card.
//
// Renders a map of area name -> list of cover entity ids (shutters, awnings,
// blinds, garage doors, etc.) as native HA tile cards, grouped under an area
// header. Tiles are laid out in a responsive, wrapping row (auto-fill grid):
// a fixed/consistent tile width, as many per row as fit the available
// width, wrapping to the next line instead of a fixed column count. Every
// tile gets exactly one feature so all tiles end up the same height —
// header (icon + name + state) plus a single row of controls underneath,
// no taller and no shorter regardless of how many buttons that feature has.
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
//   areas:
//     Living Room:
//       - cover.living_room_shutter
//       - cover.living_room_awning
//     Bedroom:
//       - cover.bedroom_blind
;(() => {
  // homeassistant.components.cover.const.CoverEntityFeature
  const SUPPORT_OPEN = 1
  const SUPPORT_CLOSE = 2
  const SUPPORT_STOP = 8
  const SUPPORT_OPEN_TILT = 16
  const SUPPORT_CLOSE_TILT = 32
  const SUPPORT_STOP_TILT = 64

  const DEFAULT_TILE_MIN_WIDTH = 160

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
        throw new Error('annika-covers-card: "areas" must be a map of area name to a list of entity ids')
      }
      this._config = config
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
      const areas = Object.values(this._config?.areas || {})
      const totalEntities = areas.reduce((sum, list) => sum + list.length, 0)
      return Math.ceil(totalEntities / 4) * 2 + areas.length
    }

    async _render() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

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

      for (const [area, entityIds] of Object.entries(this._config.areas)) {
        const header = document.createElement('div')
        header.textContent = area
        header.style.fontSize = '1.2em'
        header.style.fontWeight = '500'
        header.style.margin = '16px 0 8px 4px'
        this.appendChild(header)

        const row = document.createElement('div')
        row.className = 'annika-tile-row'

        for (const entityId of entityIds) {
          const tile = await helpers.createCardElement({
            type: 'tile',
            entity: entityId,
            features: featuresFor(this._hass, entityId),
            features_position: 'bottom',
          })
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
