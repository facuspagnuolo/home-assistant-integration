const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

test('each HD button changes only its camera and keeps other live cards mounted', async () => {
  const created = []
  const window = {
    loadCardHelpers: async () => ({
      createCardElement: async (config) => {
        const card = { config }
        created.push(card)
        return card
      },
    }),
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value },
  })
  const Card = window.AnnikaCards[0][1]
  const card = new Card()
  card._render = () => {}
  card.setConfig({ entity: 'sensor.annika_cameras' })
  card._render = () => assert.fail('HD must not rebuild the panel')
  const cameras = ['front', 'back', 'side'].map((id, index) => ({
    id, name: id, entity: `camera.outdoor_clear${index ? `_${index + 1}` : ''}`, sensors: {},
  }))
  const states = Object.fromEntries(cameras.flatMap(({ entity }) =>
    [entity, entity.replace('_clear', '_fluent')].map((id) => [id, {}])))
  card._hass = { states }
  const config = { cameras }
  const html = card._camerasHtml(config, card._texts)
  assert.equal((html.match(/data-hd=/g) || []).length, 3)
  for (const { id } of cameras) assert.ok(html.includes(`data-hd="${id}"`))

  const holders = Object.fromEntries(cameras.map(({ id }) => [id, {
    replacements: 0,
    replaceChildren(child) { this.child = child; this.replacements++ },
  }]))
  const buttons = cameras.map(({ id }) => ({
    dataset: { hd: id },
    classList: { toggle(name, on) { this[name] = on } },
    setAttribute(name, value) { this[name] = value },
    addEventListener(event, handler) { this[event] = handler },
  }))
  card.querySelector = (selector) => holders[/data-live="([^"]+)"/.exec(selector)[1]]
  card.querySelectorAll = (selector) => selector === '[data-hd]' ? buttons : []
  card._bind(config, {})
  await card._mountLive(config)
  for (const { id, entity } of cameras) {
    assert.equal(holders[id].child.config.entity, entity.replace('_clear', '_fluent'))
  }
  const backCard = holders.back.child
  const sideCard = holders.side.child
  const flush = () => new Promise((resolve) => setImmediate(resolve))

  buttons[0].click({})
  await flush()
  assert.equal(holders.front.child.config.entity, 'camera.outdoor_clear')
  assert.equal(holders.back.child, backCard)
  assert.equal(holders.back.replacements, 1)
  assert.equal(buttons[0]['aria-pressed'], 'true')
  assert.equal(buttons[0].classList.on, true)

  buttons[1].click({})
  await flush()
  assert.equal(holders.front.child.config.entity, 'camera.outdoor_clear')
  assert.equal(holders.back.child.config.entity, 'camera.outdoor_clear_2')

  buttons[0].click({})
  await flush()
  assert.equal(holders.front.child.config.entity, 'camera.outdoor_fluent')
  assert.equal(holders.back.child.config.entity, 'camera.outdoor_clear_2')
  assert.equal(buttons[0]['aria-pressed'], 'false')
  assert.equal(buttons[0].classList.on, false)
  assert.equal(holders.side.child, sideCard)
  assert.equal(holders.side.replacements, 1)
  buttons[2].click({})
  await flush()
  assert.equal(holders.side.child.config.entity, 'camera.outdoor_clear_3')
  assert.equal(created.length, 7)
})

test('a camera\'s settings are one native tile per entity of its device, with the feature its kind calls for (none for switches)', () => {
  const window = {
    Annika: {
      tileConfig: (item, options) => ({ type: 'tile', ...options, features: [...(options.features || [])], entity: item.entity, name: item.name, color: item.color }),
    },
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value },
  })
  const Card = window.AnnikaCards[0][1]
  const card = new Card()
  card._render = () => {}
  card.setConfig({ entity: 'sensor.annika_cameras' })
  const entity = (device, extra = {}) => ({ device_id: device, ...extra })
  card._hass = {
    language: 'en',
    devices: { e1: { name: 'E1 Outdoor' } },
    entities: {
      'camera.e1_clear': entity('e1'),
      'camera.e1_fluent': entity('e1'),
      'switch.e1_record': entity('e1'),
      'light.e1_floodlight': entity('e1'),
      'select.e1_floodlight_mode': entity('e1', { entity_category: 'config' }),
      'number.e1_volume': entity('e1', { entity_category: 'config' }),
      'number.e1_return_time': entity('e1', { entity_category: 'config' }),
      'button.e1_restart': entity('e1'),
      'siren.e1_siren': entity('e1'),
      'binary_sensor.e1_motion': entity('e1'),
      'switch.e1_hidden': entity('e1', { hidden: true }),
      'switch.e1_hidden_by': entity('e1', { hidden_by: 'user' }),
      'switch.other_record': entity('other'),
    },
    states: {
      'camera.e1_clear': { state: 'idle', attributes: {} },
      'camera.e1_fluent': { state: 'idle', attributes: {} },
      'switch.e1_record': { state: 'on', attributes: { friendly_name: 'E1 Outdoor Record' } },
      'light.e1_floodlight': { state: 'off', attributes: { friendly_name: 'E1 Outdoor Floodlight' } },
      'select.e1_floodlight_mode': { state: 'auto', attributes: { friendly_name: 'E1 Outdoor Floodlight Mode', options: ['auto', 'schedule'] } },
      'number.e1_volume': { state: '100', attributes: { friendly_name: 'E1 Outdoor Volume', min: 0, max: 100, step: 1 } },
      'number.e1_return_time': { state: '60', attributes: { friendly_name: 'E1 Outdoor Return Time', mode: 'box', unit_of_measurement: 's' } },
      'button.e1_restart': { state: 'unknown', attributes: { friendly_name: 'E1 Outdoor Restart', device_class: 'restart' } },
      'siren.e1_siren': { state: 'off', attributes: { friendly_name: 'E1 Outdoor Siren' } },
      'binary_sensor.e1_motion': { state: 'off', attributes: { friendly_name: 'E1 Outdoor Motion' } },
      'switch.e1_hidden': { state: 'on', attributes: {} },
      'switch.e1_hidden_by': { state: 'on', attributes: {} },
      'switch.other_record': { state: 'on', attributes: {} },
    },
  }
  const camera = { id: 'e1', name: 'E1', entity: 'camera.e1_clear', sensors: {} }
  const ids = [...card._deviceEntities(camera)]
  // Streams, hidden entities and other devices' entities are left out; config entities are kept
  // (they are most of a camera's settings); controls come before sensors.
  assert.deepEqual(ids, [
    'switch.e1_record', 'light.e1_floodlight', 'siren.e1_siren', 'select.e1_floodlight_mode',
    'number.e1_return_time', 'number.e1_volume', 'button.e1_restart', 'binary_sensor.e1_motion',
  ])
  assert.equal(card._entityName('switch.e1_record', 'e1'), 'Record')

  const tile = (id) => card._settingTile(id)
  // The tile itself is the switch: no inline toggle.
  assert.equal(tile('switch.e1_record').features.length, 0)
  assert.equal(tile('light.e1_floodlight').features.length, 0)
  assert.deepEqual(JSON.parse(JSON.stringify(tile('select.e1_floodlight_mode').features)), [{ type: 'select-options' }])
  assert.deepEqual(JSON.parse(JSON.stringify(tile('number.e1_volume').features)), [{ type: 'numeric-input', style: 'slider' }])
  assert.deepEqual(JSON.parse(JSON.stringify(tile('number.e1_return_time').features)), [{ type: 'numeric-input', style: 'buttons' }])
  assert.equal(tile('binary_sensor.e1_motion').features.length, 0)
  assert.equal(tile('switch.e1_record').color, 'primary')
  // Inside one camera's settings the device's name in front of each tile's name only takes room.
  assert.equal(tile('switch.e1_record').name, 'Record')
  assert.equal(tile('select.e1_floodlight_mode').name, 'Floodlight Mode')
  // A siren and a restart ask before they act.
  assert.ok(tile('siren.e1_siren').tap_action.confirmation.text)
  assert.ok(tile('button.e1_restart').tap_action.confirmation.text)
  assert.equal(tile('button.e1_restart').type, 'tile')

  card._settings = 'e1'
  const html = card._settingsHtml({ cameras: [camera] }, card._texts)
  assert.ok(html.includes('data-live="e1"') && html.includes('data-settings-tiles') && html.includes('data-back'))
  assert.ok(html.includes('class="annika-tile-row settings"'))
  assert.ok(!html.includes('switch.e1_hidden') && !html.includes('other_record') && !html.includes('camera.e1'))
})

test('a camera without a device has no settings, and says so', () => {
  const window = {}
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value },
  })
  const card = new (window.AnnikaCards[0][1])()
  card._render = () => {}
  card.setConfig({ entity: 'sensor.annika_cameras' })
  card._hass = { entities: {}, states: { 'camera.x': { state: 'idle', attributes: {} } } }
  const camera = { id: 'x', name: 'X', entity: 'camera.x', sensors: {} }
  assert.deepEqual([...card._deviceEntities(camera)], [])
})

test('the clip player is a modal dialog apart from the card content, so it fills the screen and survives a redraw', () => {
  const window = {}
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value },
  })
  const Card = window.AnnikaCards[0][1]
  const card = new Card()
  card._render = () => {}
  card.setConfig({ entity: 'sensor.annika_cameras' })
  card._hass = { language: 'en', states: {} }
  card._playing = { clip: { id: 'c1', camera: 'Cocina', type: 'person' }, url: '/clip.mp4', error: false }
  const html = card._playerHtml(card._texts)
  assert.ok(html.includes('<video src="/clip.mp4" controls autoplay playsinline>'))
  assert.ok(html.includes('data-close') && html.includes('data-delete="c1"'))
  assert.ok(html.includes('Cocina · Person'))
  card._playing = { clip: { id: 'c1', camera: 'Cocina', type: 'person' }, url: null, error: true }
  assert.ok(card._playerHtml(card._texts).includes('class="status"'))
  assert.ok(!readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8').includes('.annika-cams .player'))
})

test('the device name is dropped from tile names even when the registry has no device names', () => {
  const window = {}
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-cameras-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value },
  })
  const card = new (window.AnnikaCards[0][1])()
  card._render = () => {}
  card.setConfig({ entity: 'sensor.annika_cameras' })
  const named = (name) => ({ state: 'on', attributes: { friendly_name: name } })
  card._hass = {
    devices: { e6: { area_id: 'x' } },
    entities: { 'switch.a': { device_id: 'e6' }, 'switch.b': { device_id: 'e6' }, 'switch.c': { device_id: 'e6' } },
    states: { 'switch.a': named('E6 Outdoor SE PoE Record'), 'switch.b': named('E6 Outdoor SE PoE Record audio'), 'switch.c': named('E6 Outdoor SE PoE Push notifications') },
  }
  assert.equal(card._entityName('switch.a', 'e6'), 'Record')
  assert.equal(card._entityName('switch.b', 'e6'), 'Record audio')
  assert.equal(card._entityName('switch.c', 'e6'), 'Push notifications')
  // A lone entity keeps its whole name: there is nothing to tell the device's name from its own.
  card._hass.entities = { 'switch.a': { device_id: 'e6' } }
  assert.equal(card._entityName('switch.a', 'e6'), 'E6 Outdoor SE PoE Record')
})
