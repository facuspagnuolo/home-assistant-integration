// Annika lights card.
//
// Renders a map of area name -> list of entities (lights, fans, dimmers,
// switches) as native HA tile cards, grouped under an area header. Tiles
// are laid out in a responsive, wrapping row (auto-fill grid): a
// fixed/consistent tile width, as many per row as fit the available width,
// wrapping to the next line instead of a fixed column count. Every tile
// gets exactly one feature so all tiles end up the same height — header
// (icon + name + state) plus a single row of controls underneath, no
// taller and no shorter regardless of how many buttons that feature has.
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// The feature shown on each tile is derived from the entity's own
// domain/capabilities:
//   - light with a dimmable color mode -> light-brightness feature
//   - light with only "onoff" support  -> toggle feature
//   - fan reporting a speed percentage -> fan-speed feature
//   - fan without speed support        -> toggle feature
//   - anything else (switch, etc.)     -> toggle feature
//
// Usage in a dashboard view:
//   type: custom:annika-lights-card
//   tile_min_width: 160  # optional, px
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   areas:
//     Living Room:
//       - light.living_room_main
//       - entity: light.living_room_dimmer
//         name: Dimmer
//         icon: mdi:lamp
//       - fan.living_room_ceiling
//     Kitchen:
//       - switch.kitchen_lights
;(() => {
  const CARD = 'annika-lights-card'
  const DEFAULT_TILE_MIN_WIDTH = 160

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  function featuresFor(hass, entityId) {
    const domain = entityId.split('.')[0]
    const stateObj = hass.states[entityId]

    if (domain === 'light') {
      const modes = stateObj?.attributes?.supported_color_modes || []
      if (modes.some((mode) => mode !== 'onoff')) {
        return [{ type: 'light-brightness' }]
      }
      return [{ type: 'toggle' }]
    }

    if (domain === 'fan') {
      if (stateObj?.attributes?.percentage != null) {
        return [{ type: 'fan-speed' }]
      }
      return [{ type: 'toggle' }]
    }

    return [{ type: 'toggle' }]
  }

  class AnnikaLightsCard extends HTMLElement {
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

  customElements.define('annika-lights-card', AnnikaLightsCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-lights-card',
    name: 'Annika Lights',
    description: 'Lists lights/fans/switches grouped by area as native tile cards with area-appropriate features.',
  })
})()
