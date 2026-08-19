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

  function headingConfig(text) {
    return { type: 'heading', heading: text, heading_style: 'title' }
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

  window.Annika = {
    entityId,
    normalizeItem,
    normalizeItems,
    tileConfig,
    headingConfig,
    gridConfig,
    displayName,
    createHeader,
  }
})()
