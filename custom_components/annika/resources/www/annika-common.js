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
    discoverEntities,
  }
})()
