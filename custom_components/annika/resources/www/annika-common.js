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
// `toggle` also accepts an object so the switch can have its own color,
// independent of the tile's:
//
//     toggle:
//       entity: input_boolean.x
//       color: green
//
// A bare entity id string is also accepted and normalized to
// `{ entity: "<id>" }`, so both forms below are valid and can be mixed:
//
//   entities:
//     - light.living_room_main
//     - entity: light.kitchen
//       name: Kitchen
//
// `toggle` renders a switch under the tile bound to *another* entity —
// typically an `input_boolean` helper that an automation checks to decide
// whether it should react to this entity at all. The tile keeps showing its
// own state; the switch controls the helper. See
// annika-entity-toggle-feature.js.
//
// Note: `toggle` adds a feature row to the tile. On cards where tiles
// already carry a feature (lights, covers) that makes those tiles one row
// taller than their neighbours, so use it there only if every tile in the
// same row has it too.
//
// This module only exposes helpers on `window.Annika`; the cards look it up
// lazily (at render time, not at import time), so the load order between the
// card scripts does not matter.
;(() => {
  const ITEM_KEYS = ['entity', 'name', 'icon', 'color', 'toggle']

  // "entity_id" | { entity, ... } -> "entity_id"
  function entityId(value, cardName) {
    if (typeof value === 'string') return value
    if (value && typeof value === 'object' && typeof value.entity === 'string') return value.entity
    throw new Error(`${cardName}: expected an entity id string or an object with an "entity" key`)
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
        const toggle = normalized.toggle
        normalized.toggle = {
          entity: entityId(toggle, cardName),
          // A toggle without its own color follows the tile's color, and
          // falls back to the theme's active color inside the feature.
          color: (typeof toggle === 'object' ? toggle.color : undefined) ?? normalized.color,
        }
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

  // Native HA tile card config for a normalized item. Card-level defaults
  // (features, features_position, hide_state, vertical, ...) go in `options`;
  // the item's own entity/name/icon/color always win, and its optional
  // `toggle` helper is appended as an extra feature row.
  function tileConfig(item, options = {}) {
    const features = [...(options.features || [])]
    if (item.toggle) {
      features.push({
        type: 'custom:annika-entity-toggle-feature',
        entity: item.toggle.entity,
        color: item.toggle.color,
      })
    }

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

  function createHeader(text, margin = '16px 0 8px 4px') {
    const header = document.createElement('div')
    header.textContent = text
    header.style.fontSize = '1.2em'
    header.style.fontWeight = '500'
    header.style.margin = margin
    return header
  }

  // --- area discovery -----------------------------------------------------
  //
  // The frontend carries the registries on `hass`, so a card can build itself
  // from what the house actually has instead of a hand-kept entity list:
  //   hass.entities  entity_id  -> { device_id, area_id, entity_category, hidden_by, ... }
  //   hass.devices   device_id  -> { area_id, ... }
  //   hass.areas     area_id    -> { name, icon, floor_id }
  //   hass.floors    floor_id   -> { name, level }

  const UNASSIGNED_KEY = '__unassigned__'

  // For matching a config value against an area: "Living Room", "living room"
  // and "living_room" all address the same area.
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

  // Group every entity of the given domains by area.
  //
  //   domains    domains to pick up, e.g. ['light', 'switch']
  //   areas      optional list of area ids/names — restricts *and* orders
  //   include    entity ids to add even if they would be filtered out
  //   exclude    entity ids to drop, or area ids/names to drop whole
  //   overrides  { entity_id: { name?, icon?, color? } }
  //   unassigned heading for entities with no area, or false to drop them
  //
  // Returns [{ areaId, name, items: [normalized item] }] — same item shape
  // every Annika card takes, so the result drops straight into tileConfig.
  function entitiesByArea(hass, cardName, options = {}) {
    const {
      domains,
      areas,
      include = [],
      exclude = [],
      overrides = {},
      unassigned = 'Unassigned',
    } = options

    if (!Array.isArray(domains) || domains.length === 0) {
      throw new Error(`${cardName}: "domains" must be a non-empty list`)
    }

    const wantedDomains = new Set(domains)
    const forced = new Set(include.map((item) => entityId(item, cardName)))

    const excludedEntities = new Set()
    const excludedAreas = new Set()
    for (const value of exclude) {
      const id = typeof value === 'string' ? value : entityId(value, cardName)
      if (id.includes('.')) excludedEntities.add(id)
      else excludedAreas.add(slug(id))
    }

    // An explicit `areas` list both restricts and fixes the order.
    const requested = Array.isArray(areas) ? areas.map(slug) : undefined
    const areaKey = (hass_, areaId) =>
      areaId ? [slug(areaId), slug(areaLabel(hass_, areaId))] : [UNASSIGNED_KEY]

    const groups = new Map()
    for (const entity of Object.keys(hass?.states || {})) {
      const isForced = forced.has(entity)
      if (!isForced && !wantedDomains.has(entity.split('.')[0])) continue
      if (excludedEntities.has(entity)) continue
      if (!isForced && !isUserFacing(hass, entity)) continue

      const areaId = entityArea(hass, entity)
      const keys = areaKey(hass, areaId)
      if (keys.some((key) => excludedAreas.has(key))) continue
      if (requested && !keys.some((key) => requested.includes(key))) continue
      if (!areaId && unassigned === false) continue

      const key = areaId || UNASSIGNED_KEY
      if (!groups.has(key)) {
        groups.set(key, {
          areaId,
          name: areaId ? areaLabel(hass, areaId) : String(unassigned),
          // The area's own icon, so headings match what HA shows elsewhere.
          icon: areaId ? hass?.areas?.[areaId]?.icon : undefined,
          items: [],
        })
      }
      groups.get(key).items.push(normalizeItem({ entity, ...(overrides[entity] || {}) }, cardName))
    }

    const result = [...groups.values()]
    result.sort((a, b) => {
      // Entities with no area always land last, whatever the ordering.
      if (!a.areaId || !b.areaId) return !a.areaId ? 1 : -1
      if (requested) {
        const rank = (group) =>
          Math.min(...areaKey(hass, group.areaId).map((key) => {
            const index = requested.indexOf(key)
            return index === -1 ? Number.MAX_SAFE_INTEGER : index
          }))
        return rank(a) - rank(b)
      }
      return compareTuples(areaOrder(hass, a.areaId), areaOrder(hass, b.areaId))
    })

    for (const group of result) {
      group.items.sort((a, b) => displayName(hass, a).localeCompare(displayName(hass, b)))
    }

    return result.filter((group) => group.items.length > 0)
  }

  window.Annika = {
    entityId,
    normalizeItem,
    normalizeItems,
    tileConfig,
    headingConfig,
    gridConfig,
    displayName,
    createHeader,
    entityArea,
    isUserFacing,
    entitiesByArea,
  }
})()
