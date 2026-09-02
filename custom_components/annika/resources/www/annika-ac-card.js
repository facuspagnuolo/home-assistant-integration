// Annika AC (climate) card.
//
// Renders climate entities as native HA tile cards, each with only the
// features it actually supports — not every AC has fan modes, swing, or
// horizontal swing, so each feature is gated on the entity's own
// `supported_features` bitmask / mode lists instead of being hardcoded.
//
// Same layout and same config as every other Annika list card: native
// heading cards, and under each one a wrapping row of tiles that keep a
// consistent width and drop to the next line instead of squeezing.
//
// By default the card takes no entity list at all: it reads Home Assistant's
// own registries and shows every `climate` entity in the house, grouped by
// area and ordered by floor.
//
//   type: custom:annika-ac-card
//
// Everything is a knob, and the keys are the shared Annika ones:
//
//   type: custom:annika-ac-card
//   domains: [climate]           # what to pick up (default)
//   group_by: area               # area (default), category, label or none
//   color: primary               # tile color, applied to every tile (default)
//   groups: [main_bedroom, Office] # restrict *and* order; ids or names
//   exclude:                     # entity ids, or whole groups
//     - climate.server_room
//     - garage
//   include:                     # force in something that was filtered out
//     - climate.guest_unit
//   overrides:                   # per-entity, same keys as the shared shape
//     climate.main_bedroom:
//       name: Main Bedroom
//       icon: mdi:bed-double
//       color: blue
//   ungrouped: Other             # heading for the rest, or false to drop them
//   tile_min_width: 160          # px
//   heading_style: subtitle      # group headings: subtitle (default) or title
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//
// Passing `groups` as a *map* pins the card to exactly what is listed, under
// headings you choose, still as one wrapping row of tiles per group:
//
//   type: custom:annika-ac-card
//   groups:
//     Bedrooms:
//       - climate.main_bedroom
//       - entity: climate.kids_bedroom
//         name: Kids
//     Living:
//       - climate.living_room
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color? }`, mixable in the
// same list.
//
// A plain `entities` list is the named form — each unit gets its own heading
// and tile, up to 3 per row, wrapping to the next row rather than squeezing
// when the screen is too narrow for that many. This is the same thing
// annika-heating-card renders, because a thermostat and an air conditioner
// are both `climate`; what tells them apart is which entities you list:
//
//   type: custom:annika-ac-card
//   title: Aires            # optional heading above the grid
//   columns: 3              # optional, *most* units per row (default 3)
//   tile_min_width: 200     # optional px; a unit never goes narrower, it
//                           # wraps to the next row instead
//   entities:
//     - entity: climate.main_bedroom_ac
//       name: Main Bedroom
//       icon: mdi:bed-double
//     - entity: climate.guests_bedroom_ac
//       name: Guests
//       icon: mdi:bed-single
//
// A single `entity` renders one of those on its own, which is what a
// dashboard section with one AC per card uses:
//
//   type: custom:annika-ac-card
//   entity: climate.main_bedroom
//   name: Main Bedroom AC
//   icon: mdi:bed-double
;(() => {
  const CARD = 'annika-ac-card'
  const DEFAULT_DOMAINS = ['climate']

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  // The list card, shared with annika-heating-card.
  let ListCard
  function listCard() {
    if (!ListCard) {
      const { groupedTileCard, climateFeatures } = annika()
      ListCard = groupedTileCard({ card: CARD, domains: DEFAULT_DOMAINS, features: climateFeatures })
    }
    return ListCard
  }

  const DEFAULT_GRID_COLUMNS = 3
  // Wider than the 160px a light tile gets: a climate unit carries a heading,
  // a temperature stepper and a row of mode buttons, and below this its name
  // starts truncating.
  const DEFAULT_UNIT_MIN_WIDTH = 200

  class AnnikaAcCard extends HTMLElement {
    setConfig(config) {
      this._config = config

      // One `entity` is the single-unit form: a heading and its tile.
      this._single = typeof config.entity === 'string' ? annika().normalizeItem(config, CARD) : undefined
      if (this._single) {
        this._built = false
        this._render()
        return
      }

      // A plain `entities` list is the named form: each unit gets its own
      // heading and tile, laid out in a grid. It is what a dashboard writes
      // when it already knows which units it wants and what to call them, and
      // a climate tile earns its own heading — with target temperature, hvac
      // modes, fan and swing rows it is far too tall to read with its name
      // squeezed inside it.
      if (Array.isArray(config.entities)) {
        if (config.entities.length === 0) {
          throw new Error(`${CARD}: "entities" must be a non-empty list of climate entities`)
        }
        this._entities = annika().normalizeItems(config.entities, CARD)
        this._built = false
        this._cards = undefined
        this._render()
        return
      }

      // Anything else — nothing at all, `groups`, `overrides` — is discovery:
      // every climate entity in the house, grouped by area.
      if (!this._list) this._list = new (listCard())()
      this._list.setConfig(config)
      if (this._hass) this._list.hass = this._hass
      if (!this.contains(this._list)) {
        this.innerHTML = ''
        this.appendChild(this._list)
      }
    }

    set hass(hass) {
      this._hass = hass
      if (this._list) {
        this._list.hass = hass
        return
      }
      if (this._entities) {
        if (this._cards) {
          for (const element of this._cards) element.hass = hass
        } else {
          this._render()
        }
        return
      }
      if (this._tile) {
        this._tile.hass = hass
        // The heading card takes hass too — it resolves the entity's own name
        // and icon when the config names neither.
        if (this._heading) this._heading.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      if (this._list) return this._list.getCardSize()
      if (this._entities) {
        const columns = this._config?.columns || DEFAULT_GRID_COLUMNS
        return Math.ceil(this._entities.length / columns) * 3
      }
      return 3
    }

    getGridOptions() {
      // A lone unit sits in half a section, like a stock tile card does; both
      // multi-unit forms span the view.
      return this._single ? { columns: 6 } : { columns: 'full' }
    }

    getLayoutOptions() {
      return this._single ? { grid_columns: 6 } : { grid_columns: 'full' }
    }

    _render() {
      return this._entities ? this._renderGrid() : this._renderSingle()
    }

    async _renderGrid() {
      if (!this._hass || !this._config || this._built) return
      this._built = true

      const { HEADING_CSS, appendHeading } = annika()
      const helpers = await window.loadCardHelpers()

      const minWidth = this._config.tile_min_width || DEFAULT_UNIT_MIN_WIDTH
      const columns = this._config.columns || DEFAULT_GRID_COLUMNS

      // Home Assistant's own grid card is not used here, and that is the
      // whole point: it lays out exactly N columns at every width, so on a
      // phone three thermostats get squeezed into a third of a narrow screen
      // each and their names truncate to "Kitche…". This is the same wrapping
      // layout the lights and covers cards use — a unit never goes below its
      // minimum width, and one that no longer fits moves to the next row.
      //
      // `columns` is the ceiling rather than a fixed count: the track is the
      // *larger* of the minimum width and an even Nth of the row, so a wide
      // screen still shows N across and a narrow one shows as many as fit.
      const track = `max(${minWidth}px, calc((100% - ${columns - 1} * var(--ha-section-column-gap, 8px)) / ${columns}))`

      this.innerHTML = `
        <style>
          ${HEADING_CSS}
          .annika-ac-row {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(${track}, 1fr));
            column-gap: var(--ha-section-column-gap, 8px);
            /* Deliberately much larger than the column gap, and larger than
               the row gap the tile cards use.
               Every item here *starts* with a heading, and Home Assistant's
               heading card carries about 27px of its own padding underneath.
               With the plain 8px row gap that left roughly 5px of air above a
               heading against 27px below it, so a second-row heading read as
               belonging to the card above rather than to its own. The gap
               above has to beat the padding below for the heading to attach
               downwards, which is the whole job of a heading. */
            row-gap: calc(var(--ha-section-row-gap, 8px) * 4);
          }
          /* Grid items refuse to shrink past their content otherwise, which
             is what turns a too-wide tile into a sideways-scrolling row. */
          .annika-ac-row > * {
            min-width: 0;
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

      if (this._config.title) {
        this._cards.push(
          await appendHeading(this, helpers, this._hass, this._config.title, { style: 'title' }),
        )
      }

      // Each unit is this same card in its single form, so the heading and
      // the feature detection live in exactly one place.
      const row = document.createElement('div')
      row.className = 'annika-ac-row'
      for (const item of this._entities) {
        row.appendChild(await build({ type: `custom:${CARD}`, ...item }))
      }
      this.appendChild(row)
    }

    async _renderSingle() {
      if (!this._hass || !this._single || this._built) return
      this._built = true

      const { tileConfig, HEADING_CSS, appendHeading, climateFeatures, displayName } = annika()
      const helpers = await window.loadCardHelpers()

      this.innerHTML = `<style>${HEADING_CSS}</style>`

      // Home Assistant's own heading card, not a <div> of ours: it carries
      // the typography, spacing and icon treatment a stock dashboard uses, so
      // this reads the same as a hand-built card sitting next to it — and
      // follows the theme instead of hard-coding a font size and a colour.
      // `subtitle` is what names a group on a stock dashboard.
      this._heading = await appendHeading(
        this,
        helpers,
        this._hass,
        displayName(this._hass, this._single),
        { style: 'subtitle', icon: this._single.icon },
      )

      // The name and icon are already in the header above, so the tile only
      // keeps the entity's color and its auto-detected features.
      this._tile = await helpers.createCardElement(
        tileConfig(
          { entity: this._single.entity, color: this._single.color },
          { features: climateFeatures(this._hass, this._single.entity) },
        ),
      )
      this._tile.hass = this._hass
      this.appendChild(this._tile)
    }
  }

  customElements.define('annika-ac-card', AnnikaAcCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-ac-card',
    name: 'Annika AC',
    description:
      'Climate entities discovered from the registries and grouped by area, as native tile cards with auto-detected features.',
  })
})()
