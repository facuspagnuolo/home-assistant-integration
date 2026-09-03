// Annika shared card helpers.
//
// Every Annika card takes the entities it renders in the same shape:
//
//   - entity: light.living_room_main   # required
//     name: Main Light                 # optional, overrides the friendly name
//     icon: mdi:lamp                   # optional, overrides the default icon
//     color: amber                     # optional, tile accent color
//     toggle: input_boolean.x          # optional, see below
//
// `toggle` also accepts an object, so the control can have its own color
// (independent of the tile's) and pick how it looks:
//
//     toggle:
//       entity: input_boolean.x   # optional, defaults to the tile's entity
//       style: checkbox           # optional, one of the four below
//       color: green
//
//     inline         (default) a small checkbox pulled into the tile's own
//                    row, so the tile stays one row tall
//     inline-switch  Home Assistant's own ha-control-switch, positioned into
//                    the tile's row. It is wide, so give those tiles a full
//                    row to sit in
//     checkbox       the same checkbox, on a row of its own below
//     switch         Home Assistant's own toggle feature, on its own row —
//                    the very same control a light tile gets
//
// `switch` on a toggle that controls the tile's own entity and asks for no
// colour is rendered as HA's built-in `toggle` feature, not as ours: it is
// the same thing, so there is no reason to hand-roll it. Everything else
// needs the custom feature — the built-in one only knows about the tile's own
// entity, always takes a row of its own, and paints itself with the tile's
// state colour.
//
// `toggle: false` means no toggle at all — which is not the same as leaving
// it out. Some cards add one by themselves (the alarm card pairs each sensor
// with the participation switch the Annika integration made for it), and
// `false` is how they are told not to.
//
// A bare entity id string is also accepted and normalized to
// `{ entity: "<id>" }`, so both forms below are valid and can be mixed:
//
//   entities:
//     - light.living_room_main
//     - entity: light.kitchen
//       name: Kitchen
//
// `toggle` renders a control on the tile bound to *another* entity —
// typically an `input_boolean` helper that an automation checks to decide
// whether it should react to this entity at all. The tile keeps showing its
// own state; the control flips the helper. Naming no entity points it at the
// tile's own entity instead, which is how a siren gets a switch for itself.
// See annika-entity-toggle-feature.js.
//
// Note: the `checkbox` and `switch` styles add a row to the tile. On cards
// where tiles already carry a feature (lights, covers) that makes those tiles
// one row taller than their neighbours, so use them there only if every tile
// in the same row has one too. The two `inline` styles do not have this
// problem — that is what they are for.
//
// This module only exposes helpers on `window.Annika`, and the cards look it
// up lazily rather than at import time — but that alone was not enough. The
// files are injected with `add_extra_js_url`, which gives no ordering
// guarantee, so a card could register itself, have Lovelace build it, and
// only then find `window.Annika` missing: `setConfig` threw and Lovelace
// showed a permanent "Configuration error" on every cold load.
//
// So the cards no longer register themselves at all: they declare themselves
// on `window.AnnikaCards` and this file registers them once the helpers are in
// place. See the bottom of this file. An unregistered tag is the failure mode
// Lovelace recovers from by itself, by waiting on `customElements.whenDefined`
// and rebuilding.
;(() => {
  const ITEM_KEYS = ['entity', 'name', 'icon', 'color', 'toggle']

  // Kept in step with annika-entity-toggle-feature.js, which rejects anything
  // else. Validated here too so a typo in a dashboard fails while the card is
  // being configured, naming the card and the styles, instead of surfacing
  // later as a broken tile.
  const TOGGLE_STYLES = ['inline', 'inline-switch', 'checkbox', 'switch']

  // "entity_id" | { entity, ... } -> "entity_id"
  function entityId(value, cardName) {
    if (typeof value === 'string') return value
    if (value && typeof value === 'object' && typeof value.entity === 'string') return value.entity
    throw new Error(`${cardName}: expected an entity id string or an object with an "entity" key`)
  }

  // The `toggle` key of an item, normalized.
  //
  //   false | null            -> false, meaning "no toggle", explicitly
  //   "entity_id"             -> { entity }
  //   { entity?, style?, color? }
  //
  // `entity` is optional: a toggle that names none controls the tile's own
  // entity. `false` is returned rather than dropped so a card can tell "the
  // user said no" apart from "the user said nothing", which is what lets the
  // alarm card skip a sensor when auto-pairing its participation switch.
  function normalizeToggle(value, item, cardName) {
    if (value === false || value === null) return false

    const object = typeof value === 'object' && value !== null
    if (!object && typeof value !== 'string') {
      throw new Error(
        `${cardName}: "toggle" must be an entity id, false, or ` +
          '{ entity?, style?, color? }',
      )
    }

    const style = object ? value.style : undefined
    if (style !== undefined && !TOGGLE_STYLES.includes(style)) {
      throw new Error(
        `${cardName}: "toggle.style" must be one of ${TOGGLE_STYLES.join(', ')}`,
      )
    }

    const entity = object ? value.entity : value
    if (entity !== undefined && typeof entity !== 'string') {
      throw new Error(`${cardName}: "toggle.entity" must be an entity id`)
    }

    return {
      entity,
      style,
      // A toggle without its own color follows the tile's color, and falls
      // back to `primary` inside the feature.
      color: (object ? value.color : undefined) ?? item.color,
    }
  }

  // "entity_id" | { entity, name?, icon?, color?, toggle? } -> normalized object
  function normalizeItem(item, cardName) {
    if (typeof item === 'string') {
      return { entity: item }
    }
    if (item && typeof item === 'object' && typeof item.entity === 'string') {
      const normalized = {}
      for (const key of ITEM_KEYS) {
        if (item[key] !== undefined) normalized[key] = item[key]
      }
      if (normalized.toggle !== undefined) {
        normalized.toggle = normalizeToggle(normalized.toggle, normalized, cardName)
      }
      return normalized
    }
    throw new Error(
      `${cardName}: every entry must be an entity id string or an object with an "entity" key ` +
        '({ entity, name?, icon?, color?, toggle? })',
    )
  }

  function normalizeItems(items, cardName, key = 'entities') {
    if (!Array.isArray(items)) {
      throw new Error(
        `${cardName}: "${key}" must be a list of entity ids or { entity, name?, icon?, color?, toggle? } objects`,
      )
    }
    return items.map((item) => normalizeItem(item, cardName))
  }

  // The feature config for an item's `toggle`.
  //
  // Home Assistant's own `toggle` feature is used wherever it can be, so a
  // siren ends up with the exact control a light has — same element, same
  // behaviour, none of our code in the way. It only fits when all three of
  // these hold, and each rules it out for a real reason:
  //
  //   - the control is for the tile's own entity. The native feature has no
  //     concept of a second entity, which is the whole reason the custom one
  //     exists: an alarm sensor's tile shows the sensor while its control
  //     flips the participation switch.
  //   - the style is `switch`. The native feature always takes a row of its
  //     own and that is not configurable, so nothing inline can be it. The
  //     `inline-switch` style still renders Home Assistant's own
  //     `ha-control-switch` — just positioned into the tile's row by us.
  //   - no colour was asked for. The native feature paints itself with the
  //     tile's state colour and takes no colour of its own.
  function toggleFeature(item) {
    const entity = item.toggle.entity || item.entity
    const native =
      entity === item.entity &&
      item.toggle.style === 'switch' &&
      item.toggle.color === undefined

    if (native) return { type: 'toggle' }

    return {
      type: 'custom:annika-entity-toggle-feature',
      entity,
      style: item.toggle.style,
      color: item.toggle.color,
    }
  }

  // Native HA tile card config for a normalized item. Card-level defaults
  // (features, features_position, hide_state, vertical, ...) go in `options`;
  // the item's own entity/name/icon/color always win, and its optional
  // `toggle` helper is appended as an extra feature row.
  function tileConfig(item, options = {}) {
    const features = [...(options.features || [])]
    if (item.toggle) features.push(toggleFeature(item))

    return {
      type: 'tile',
      hide_state: false,
      vertical: false,
      features_position: 'bottom',
      ...options,
      features,
      entity: item.entity,
      name: item.name,
      icon: item.icon,
      color: item.color,
    }
  }

  // Home Assistant's own heading card, not a hand-rolled <div>: it carries
  // the typography, spacing and icon treatment a hand-built dashboard gets,
  // so an Annika card sitting next to a stock one reads the same.
  //   style  'title' (large, primary text) | 'subtitle' (small, secondary) —
  //          area/group headings on a stock dashboard are subtitles
  //   icon   optional, e.g. the area's own icon from the registry
  function headingConfig(text, { style = 'title', icon } = {}) {
    const config = { type: 'heading', heading: text, heading_style: style }
    if (icon) config.icon = icon
    return config
  }

  function gridConfig(cards, columns = 2) {
    return { type: 'grid', columns, square: false, cards }
  }

  // Name to show in a card-drawn header (not a tile): explicit name, else the
  // entity's friendly name, else the raw entity id.
  function displayName(hass, item) {
    return item.name || hass?.states?.[item.entity]?.attributes?.friendly_name || item.entity
  }

  // The one heading treatment every Annika card uses.
  //
  // This lived as four identical copies across the cards, and three others
  // built their headings some other way — a styled <div> here, a bare heading
  // card there. The result was headings that looked subtly different from one
  // view to the next: same font, but 62px of air under the heading on the
  // lights view against 97px on the AC one. There is nothing to keep in step
  // by hand now; a card either uses `appendHeading` or it has no heading.
  //
  // Include HEADING_CSS in the card's own <style> block, then append with
  // `appendHeading`. Both are needed: the class is what the rules apply to.
  const HEADING_CSS = `
    .annika-heading {
      display: block;
    }
    .annika-heading:not(:first-child) {
      margin-top: var(--ha-section-row-gap, 8px);
    }
  `

  // Appends Home Assistant's own heading card to `host`, carrying the shared
  // class. Returns the element so the caller can keep it for hass updates.
  //   style  'title' (large, primary) | 'subtitle' (small, secondary) —
  //          group headings on a stock dashboard are subtitles
  async function appendHeading(host, helpers, hass, text, { style = 'subtitle', icon } = {}) {
    const element = await helpers.createCardElement(headingConfig(text, { style, icon }))
    element.hass = hass
    element.classList.add('annika-heading')
    host.appendChild(element)
    return element
  }

  // --- entity discovery ---------------------------------------------------
  //
  // The frontend carries Home Assistant's registries on `hass`, so a card can
  // build itself from what the house actually has instead of a hand-kept
  // entity list:
  //   hass.entities  entity_id -> { device_id, area_id, categories, labels,
  //                                 entity_category, hidden_by, disabled_by }
  //   hass.devices   device_id -> { area_id }
  //   hass.areas     area_id   -> { name, icon, floor_id }
  //   hass.floors    floor_id  -> { name, level }
  //
  // Categories and labels are not on `hass` — they live in their own
  // registries, read over the websocket and cached per connection. Older
  // Home Assistant versions do not have those commands; a card that asks for
  // them there simply ends up with everything ungrouped instead of failing.

  const UNGROUPED_KEY = '__ungrouped__'
  const GROUP_MODES = ['area', 'category', 'label', 'none']

  // For matching a config value against a group: "Living Room", "living room"
  // and "living_room" all address the same one.
  function slug(value) {
    return String(value).trim().toLowerCase().replace(/[^a-z0-9]+/g, '_')
  }

  // An entity's area is its own if it has one, otherwise its device's.
  function entityArea(hass, entity) {
    const entry = hass?.entities?.[entity]
    if (!entry) return undefined
    return entry.area_id || hass?.devices?.[entry.device_id]?.area_id || undefined
  }

  // Entities the user is not meant to see on a dashboard: hidden, disabled, or
  // the config/diagnostic entities every integration ships. Anything missing
  // from the registry (YAML helpers, templates without a unique_id) has
  // nothing marking it either way, so it is kept.
  function isUserFacing(hass, entity) {
    const entry = hass?.entities?.[entity]
    if (!entry) return true
    return !entry.hidden_by && !entry.disabled_by && !entry.entity_category
  }

  function areaLabel(hass, areaId) {
    return hass?.areas?.[areaId]?.name || areaId
  }

  // Areas come out of the registry unordered; sort them the way they read in
  // the house — by floor, then by name.
  function areaOrder(hass, areaId) {
    const area = hass?.areas?.[areaId]
    const floor = area?.floor_id ? hass?.floors?.[area.floor_id] : undefined
    return [floor?.level ?? 0, floor?.name || '', area?.name || areaId]
  }

  function compareTuples(a, b) {
    for (let i = 0; i < a.length; i += 1) {
      if (a[i] === b[i]) continue
      return a[i] < b[i] ? -1 : 1
    }
    return 0
  }

  // One in-flight request per connection and registry, so ten cards on a
  // dashboard cost one websocket round trip, not ten.
  const registryCache = new WeakMap()

  function fetchRegistry(hass, key, message) {
    const connection = hass?.connection
    if (!connection || typeof hass.callWS !== 'function') return Promise.resolve([])

    let cache = registryCache.get(connection)
    if (!cache) {
      cache = new Map()
      registryCache.set(connection, cache)
    }
    if (!cache.has(key)) {
      // A Home Assistant without this command is not an error here: it just
      // means the card cannot group by it, so it degrades to ungrouped.
      cache.set(key, Promise.resolve(hass.callWS(message)).catch(() => []))
    }
    return cache.get(key)
  }

  // Group every entity of the given domains, by area, category or label.
  //
  //   domains    domains to pick up, e.g. ['light', 'switch']
  //   groupBy    'area' (default) | 'category' | 'label' | 'none'
  //   groups     optional list of group ids/names — restricts *and* orders
  //   include    entity ids to add even if they would be filtered out
  //   exclude    entity ids to drop, or group ids/names to drop whole
  //   overrides  { entity_id: { name?, icon?, color?, toggle? } }
  //   ungrouped  heading for entities in no group, or false to drop them
  //   categoryScope  category registry scope (defaults to the first domain)
  //
  // Returns [{ key, name, icon, items: [normalized item] }] — same item shape
  // every Annika card takes, so the result drops straight into tileConfig.
  // When nothing turned out to be grouped, the single group comes back with
  // no name, so the card renders a plain list instead of a lone "Other".
  async function discoverEntities(hass, cardName, options = {}) {
    const {
      domains,
      groupBy = 'area',
      groups,
      include = [],
      exclude = [],
      overrides = {},
      ungrouped = 'Other',
      categoryScope,
    } = options

    if (!Array.isArray(domains) || domains.length === 0) {
      throw new Error(`${cardName}: "domains" must be a non-empty list`)
    }
    let mode = String(groupBy)
    if (!GROUP_MODES.includes(mode)) {
      throw new Error(`${cardName}: "group_by" must be one of ${GROUP_MODES.join(', ')}`)
    }

    // Group id -> { name, icon }, for the modes that need a registry.
    const scope = categoryScope || domains[0]
    const index = new Map()
    if (mode === 'category') {
      const list = await fetchRegistry(hass, `category:${scope}`, {
        type: 'config/category_registry/list',
        scope,
      })
      for (const entry of list || []) index.set(entry.category_id, entry)
    } else if (mode === 'label') {
      const list = await fetchRegistry(hass, 'label', { type: 'config/label_registry/list' })
      for (const entry of list || []) index.set(entry.label_id, entry)
    }

    // Without the registry there are no names for the ids the entities carry,
    // and grouping by raw ids ("c_01f3...") is worse than not grouping. This
    // is the older-Home-Assistant path, and also the nothing-is-tagged-yet one.
    if (index.size === 0 && (mode === 'category' || mode === 'label')) mode = 'none'

    const groupsOf = (entity) => {
      if (mode === 'none') return []
      if (mode === 'area') {
        const areaId = entityArea(hass, entity)
        return areaId ? [areaId] : []
      }
      const entry = hass?.entities?.[entity]
      if (!entry) return []
      if (mode === 'category') {
        const categoryId = entry.categories?.[scope]
        return categoryId ? [categoryId] : []
      }
      return entry.labels || []
    }

    const nameOf = (id) => (mode === 'area' ? areaLabel(hass, id) : index.get(id)?.name || id)
    const iconOf = (id) => (mode === 'area' ? hass?.areas?.[id]?.icon : index.get(id)?.icon)
    const keysOf = (id) => [slug(id), slug(nameOf(id))]
    const orderOf = (id) => (mode === 'area' ? areaOrder(hass, id) : [0, '', nameOf(id)])

    const wantedDomains = new Set(domains)
    const forced = new Set(include.map((item) => entityId(item, cardName)))

    const excludedEntities = new Set()
    const excludedGroups = new Set()
    for (const value of exclude) {
      const id = typeof value === 'string' ? value : entityId(value, cardName)
      if (id.includes('.')) excludedEntities.add(id)
      else excludedGroups.add(slug(id))
    }

    // An explicit list both restricts and fixes the order.
    const requested = Array.isArray(groups) ? groups.map(slug) : undefined
    const rank = (id) => {
      const positions = keysOf(id)
        .map((key) => requested.indexOf(key))
        .filter((position) => position !== -1)
      return positions.length ? Math.min(...positions) : -1
    }

    const buckets = new Map()
    for (const entity of Object.keys(hass?.states || {})) {
      const isForced = forced.has(entity)
      if (!isForced && !wantedDomains.has(entity.split('.')[0])) continue
      if (excludedEntities.has(entity)) continue
      if (!isForced && !isUserFacing(hass, entity)) continue

      // Excluding a group hides what is in it: an entity in an excluded group
      // disappears rather than falling through to the ungrouped bucket.
      const candidates = groupsOf(entity)
      if (candidates.some((id) => keysOf(id).some((k) => excludedGroups.has(k)))) continue

      // An entity can carry several labels; it still belongs to exactly one
      // group here, so it never shows up twice. With an explicit list the
      // earliest one listed wins, otherwise the first one it carries.
      let groupId
      if (requested) {
        const ranked = candidates.map((id) => [rank(id), id]).filter(([r]) => r !== -1)
        if (!ranked.length) continue
        ranked.sort((a, b) => a[0] - b[0])
        groupId = ranked[0][1]
      } else {
        groupId = candidates[0]
      }

      if (!groupId && ungrouped === false) continue

      const key = groupId || UNGROUPED_KEY
      if (!buckets.has(key)) {
        buckets.set(key, {
          key: groupId,
          name: groupId ? nameOf(groupId) : String(ungrouped),
          // The group's own icon, so headings match what HA shows elsewhere.
          icon: groupId ? iconOf(groupId) : undefined,
          items: [],
        })
      }
      buckets.get(key).items.push(normalizeItem({ entity, ...(overrides[entity] || {}) }, cardName))
    }

    const result = [...buckets.values()]
    result.sort((a, b) => {
      // Ungrouped entities always land last, whatever the ordering.
      if (!a.key || !b.key) return !a.key ? 1 : -1
      if (requested) return rank(a.key) - rank(b.key)
      return compareTuples(orderOf(a.key), orderOf(b.key))
    })

    for (const group of result) {
      group.items.sort((a, b) => displayName(hass, a).localeCompare(displayName(hass, b)))
    }

    const nonEmpty = result.filter((group) => group.items.length > 0)

    // Nothing is actually grouped — no categories set, no areas assigned. A
    // single heading reading "Other" over the whole card is noise, so drop it
    // and let the card render a plain list.
    if (nonEmpty.length === 1 && !nonEmpty[0].key) nonEmpty[0].name = undefined

    return nonEmpty
  }

  // --- grouped tile card ---------------------------------------------------
  //
  // The layout every Annika list card shares: native heading cards, and under
  // each one a wrapping row of native tile cards — a consistent tile width,
  // as many per row as fit, dropping to the next line instead of squeezing.
  // Entities come from `discoverEntities` unless the config pins them.
  //
  //   card      element name, for error messages
  //   domains   default domains to discover
  //   groupBy   default grouping axis
  //   features  (hass, entity) -> tile features for that entity
  //   color     default tile color
  //
  // Returns a class ready for customElements.define.
  function groupedTileCard({ card: CARD, domains, groupBy = 'area', features, color: defaultColor = 'primary' }) {
    const DEFAULT_TILE_MIN_WIDTH = 160
    const DEFAULT_HEADING_STYLE = 'subtitle'

    return class extends HTMLElement {
      setConfig(config) {
        // `groups` is the shared key; a map pins the card to exactly what is
        // listed, a list restricts and orders what discovery finds.
        if (config.groups !== undefined && typeof config.groups !== 'object') {
          throw new Error(`${CARD}: "groups" must be a list of group ids/names, or a map of heading to entities`)
        }

        this._config = config
        if (Array.isArray(config.entities)) {
          if (config.entities.length === 0) {
            throw new Error(`${CARD}: "entities" must be a non-empty list of entities`)
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
        // when they change — that is what makes a newly added entity appear.
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
          for (const element of this._cards) element.hass = hass
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
        return { columns: 'full' }
      }

      getLayoutOptions() {
        return { grid_columns: 'full' }
      }

      _discover() {
        if (this._manualGroups) return Promise.resolve(this._manualGroups)

        return discoverEntities(this._hass, CARD, {
          domains: this._config.domains || domains,
          groupBy: this._config.group_by || groupBy,
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

        const helpers = await window.loadCardHelpers()
        const minWidth = this._config.tile_min_width || DEFAULT_TILE_MIN_WIDTH
        const color = this._config.color === undefined ? defaultColor : this._config.color
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

        const addHeading = async (text, style, icon) =>
          this._cards.push(await appendHeading(this, helpers, this._hass, text, { style, icon }))

        if (this._config.title) await addHeading(this._config.title, 'title')

        for (const group of this._groups) {
          if (group.name) await addHeading(group.name, headingStyle, group.icon)

          const row = document.createElement('div')
          row.className = 'annika-tile-row'

          for (const item of group.items) {
            // The card-level color is a default: an item's own `color` wins.
            row.appendChild(
              await build(tileConfig({ color, ...item }, { features: features(this._hass, item.entity) })),
            )
          }

          this.appendChild(row)
        }
      }
    }
  }

  // homeassistant.components.climate.const.ClimateEntityFeature
  const CLIMATE_TARGET_TEMPERATURE = 1
  const CLIMATE_TARGET_TEMPERATURE_RANGE = 2
  const CLIMATE_FAN_MODE = 8
  const CLIMATE_SWING_MODE = 32
  const CLIMATE_SWING_HORIZONTAL_MODE = 512

  // Only the features the entity actually supports — not every AC has fan
  // modes, swing, or horizontal swing, so each one is gated on the entity's
  // own supported_features bitmask / mode lists instead of being hardcoded.
  function climateFeatures(hass, entity) {
    const stateObj = hass?.states?.[entity]
    const supported = stateObj?.attributes?.supported_features || 0
    const features = []

    if (supported & CLIMATE_TARGET_TEMPERATURE || supported & CLIMATE_TARGET_TEMPERATURE_RANGE) {
      features.push({ type: 'target-temperature' })
    }
    if ((stateObj?.attributes?.hvac_modes || []).length > 1) {
      features.push({ type: 'climate-hvac-modes' })
    }
    if (supported & CLIMATE_FAN_MODE) {
      features.push({ style: 'icons', type: 'climate-fan-modes' })
    }
    if (supported & CLIMATE_SWING_MODE) {
      features.push({ style: 'icons', type: 'climate-swing-modes' })
    }
    if (supported & CLIMATE_SWING_HORIZONTAL_MODE) {
      features.push({ style: 'icons', type: 'climate-swing-horizontal-modes' })
    }

    return features
  }

  window.Annika = {
    entityId,
    normalizeItem,
    normalizeItems,
    tileConfig,
    headingConfig,
    gridConfig,
    displayName,
    HEADING_CSS,
    appendHeading,
    entityArea,
    isUserFacing,
    discoverEntities,
    groupedTileCard,
    climateFeatures,
  }

  // --- card registration -------------------------------------------------
  //
  // The card files do not call `customElements.define` themselves. They cannot
  // safely: `add_extra_js_url` gives no ordering guarantee, so a card file can
  // run before this one. A card registered that early can be built by Lovelace
  // before `window.Annika` exists, and its `setConfig` then throws for want of
  // these helpers — which Lovelace turns into a "Configuration error" card
  // that only a page reload clears. That is what made every Annika card fail
  // on the first load of a session.
  //
  // So each card only *declares* itself, in one line:
  //
  //   ;(window.AnnikaCards ||= []).push(['annika-lights-card', AnnikaLightsCard])
  //
  // and registering happens here, where the helpers are known to exist. Cards
  // that loaded first are sitting in the array and get drained now; cards that
  // load later find `push` already replaced by the registering version, so
  // both orders end in the same place and neither needs to know which it is.
  //
  // The optional third element lists other Annika tags the card builds and so
  // needs defined — the heating card builds ac cards.
  function defineCard([tag, cls, deps = []]) {
    const define = () => {
      if (!customElements.get(tag)) customElements.define(tag, cls)
    }
    if (deps.every((dep) => customElements.get(dep))) return define()
    Promise.all(deps.map((dep) => customElements.whenDefined(dep))).then(define)
  }

  const declared = window.AnnikaCards || []
  window.AnnikaCards = { push: defineCard }
  declared.forEach(defineCard)
})()
