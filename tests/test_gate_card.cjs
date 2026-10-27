const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

const ENTITIES = {
  cover: 'cover.gate',
  moving: 'binary_sensor.gate_moving',
  open_seconds: 'number.gate_opening_time',
  close_seconds: 'number.gate_closing_time',
  threshold: 'number.gate_power_threshold',
  auto_off: 'number.gate_relay_auto_off',
  closed_inverted: 'switch.gate_invert_closed_sensor',
  open_inverted: 'switch.gate_invert_open_sensor',
  calibrate: 'button.gate_calibrate',
  notify: null,
  power: 'sensor.gate_pm_power',
  closed: 'binary_sensor.gate_closed',
  open: 'binary_sensor.gate_open',
  pulse: 'switch.porton',
}

function load() {
  class Element {
    constructor() {
      this.classList = { add() {} }
      this.style = { setProperty() {} }
      this.children = []
    }
    appendChild(child) { this.children.push(child) }
    addEventListener() {}
  }
  const configs = []
  const window = {
    Annika: {
      tileConfig: (item, options) => ({ type: 'tile', ...options, ...item }),
      headingConfig: (heading) => ({ type: 'heading', heading }),
      gridConfig: (cards, columns) => ({ type: 'grid', cards, columns }),
      language: (hass, config) => (config && config.language) || (hass && hass.language) || 'en',
      textsFor: (texts, lang) => texts[lang] || texts.en,
      HEADING_CSS: '',
      HISTORY_CSS: '',
    },
    loadCardHelpers: async () => ({
      createCardElement(config) {
        configs.push(config)
        return new Element()
      },
    }),
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-gate-card.js'), 'utf8'), {
    window,
    HTMLElement: Element,
    document: { createElement: () => new Element() },
  })
  const Card = window.AnnikaCards.find(([name]) => name === 'annika-gate-card')[1]
  const card = new Card()
  card.innerHTML = ''
  card.appendChild = () => {}
  return { card, configs, window }
}

async function built(entities, language = 'en') {
  const { card, configs, window } = load()
  card._config = { entity: 'sensor.gate', language }
  card._hass = { language, states: {} }
  card._resolveTexts()
  await card._build({ entities })
  return { card, configs, window }
}

const tiles = (configs) => configs.filter((config) => config.type === 'grid').flatMap((grid) => grid.cards)

test('registers itself as a card', () => {
  const { window } = load()
  assert.ok(window.AnnikaCards.some(([name]) => name === 'annika-gate-card'))
  assert.ok(window.customCards.some((card) => card.type === 'annika-gate-card'))
})

test('the cover is a native tile with open, close, stop and position', async () => {
  const { configs } = await built(ENTITIES)
  const cover = tiles(configs).find((tile) => tile.entity === 'cover.gate')
  assert.deepEqual([...cover.features.map((feature) => feature.type)], ['cover-open-close', 'cover-position'])
})

test('the four source entities and the motor show as tiles to monitor', async () => {
  const { configs } = await built(ENTITIES)
  const shown = tiles(configs).map((tile) => tile.entity)
  for (const entity of ['sensor.gate_pm_power', 'binary_sensor.gate_closed', 'binary_sensor.gate_open', 'switch.porton', 'binary_sensor.gate_moving']) {
    assert.ok(shown.includes(entity), entity)
  }
})

test('times and threshold are steppers, and calibrate presses its button', async () => {
  const { configs } = await built(ENTITIES)
  const all = tiles(configs)
  for (const entity of ['number.gate_opening_time', 'number.gate_closing_time', 'number.gate_power_threshold', 'number.gate_relay_auto_off']) {
    const tile = all.find((candidate) => candidate.entity === entity)
    assert.equal(tile.features[0].type, 'numeric-input', entity)
    assert.equal(tile.features[0].style, 'buttons', entity)
  }
  const calibrate = all.find((tile) => tile.entity === 'button.gate_calibrate')
  assert.equal(calibrate.tap_action.perform_action, 'button.press')
  assert.equal(calibrate.tap_action.target.entity_id, 'button.gate_calibrate')
})

test('the notifications tile is there only when the integration has one', async () => {
  const without = await built(ENTITIES)
  assert.ok(!tiles(without.configs).some((tile) => tile.entity === 'switch.gate_notifications'))
  const withNotify = await built({ ...ENTITIES, notify: 'switch.gate_notifications' })
  assert.ok(tiles(withNotify.configs).some((tile) => tile.entity === 'switch.gate_notifications'))
})

test('history draws the consumption, the motor and the cover', async () => {
  const { configs } = await built(ENTITIES)
  const history = configs.flatMap((config) => config.cards || []).find((config) => config.type === 'history-graph')
  assert.deepEqual([...history.entities.map((item) => item.entity)], ['sensor.gate_pm_power', 'binary_sensor.gate_moving', 'cover.gate'])
})

test('the card is built again only when the entities map changes', () => {
  const { card } = load()
  card._config = { entity: 'sensor.gate' }
  card._entity = 'sensor.gate'
  card._hass = { language: 'en', states: { 'sensor.gate': { state: 'closed', attributes: { entities: ENTITIES, position: 0 } } } }
  card._resolveTexts()
  const first = card._structureNow()
  card._hass.states['sensor.gate'] = { state: 'opening', attributes: { entities: ENTITIES, position: 40 } }
  assert.equal(card._structureNow(), first)
  card._hass.states['sensor.gate'] = { state: 'opening', attributes: { entities: { ...ENTITIES, notify: 'switch.n' }, position: 40 } }
  assert.notEqual(card._structureNow(), first)
})

function status(state, attributes, language = 'en') {
  const { card } = load()
  card._config = { entity: 'sensor.gate', language }
  card._hass = { language, states: {} }
  card._resolveTexts()
  return card._statusLines({ state, attributes })
}

test('the status line says where the gate is and its last move', () => {
  const html = status('stopped', {
    position: 42.4,
    last_move: { direction: 'opening', seconds: 7.5, from: 0, to: 42.4, complete: false },
    calibration: { status: 'idle' },
  })
  assert.match(html, /Position 42%/)
  assert.match(html, /opening/)
  assert.match(html, /7\.5 s/)
  assert.match(html, /partial/)
})

test('calibration shows its progress, its result and why it failed', () => {
  assert.match(status('calibrating', { position: 0, calibration: { status: 'running' } }), /Calibrating/)
  const ok = status('closed', { position: 0, calibration: { status: 'ok', open_seconds: 17.2, close_seconds: 16.8, threshold: 65 } })
  assert.match(ok, /17\.2 s/)
  assert.match(ok, /16\.8 s/)
  assert.match(ok, /65 W/)
  const failed = status('stopped', { position: 50, calibration: { status: 'failed', message: 'no_motion' } })
  assert.match(failed, /Calibration failed: the pulse did not move it/)
})

test('texts follow the language', () => {
  const html = status('closed', { position: 0, calibration: { status: 'failed', message: 'never_stopped' } }, 'es')
  assert.match(html, /Posición 0%/)
  assert.match(html, /Falló la calibración: nunca se detuvo/)
})

test('a missing sensor says what to check instead of failing', async () => {
  const { card } = load()
  card._config = { entity: 'sensor.gate' }
  card._hass = { language: 'en', states: {} }
  card._resolveTexts()
  await card._render()
  assert.match(card.innerHTML, /gate/)
  assert.match(card.innerHTML, /not found/)
})

test('the inversion switches are tiles next to the sensors', async () => {
  const { configs } = await built(ENTITIES)
  const shown = tiles(configs).map((tile) => tile.entity)
  assert.ok(shown.includes('switch.gate_invert_closed_sensor'))
  assert.ok(shown.includes('switch.gate_invert_open_sensor'))
})

const PRESENT = {
  'switch.porton': { state: 'off' },
  'sensor.gate_pm_power': { state: '0' },
  'binary_sensor.gate_closed': { state: 'on' },
  'binary_sensor.gate_open': { state: 'off' },
}

function warnings(states, attributes, language = 'en', present = true) {
  const { card } = load()
  card._config = { entity: 'sensor.gate', language }
  card._hass = { language, states: present ? { ...PRESENT, ...states } : states }
  card._resolveTexts()
  return card._warnings({ entities: ENTITIES, pulse_seconds: 0.7, ...attributes }).join('')
}

test('a relay with no auto-off is flagged, with a one-tap fix', () => {
  const html = warnings({ 'number.gate_relay_auto_off': { state: '0' } }, {})
  assert.match(html, /no auto-off/)
  assert.match(html, /data-entity="number\.gate_relay_auto_off" data-value="1.4"/)
  assert.match(html, /Use 1\.4 s/)
})

test('an auto-off shorter than the pulse is flagged', () => {
  const html = warnings({ 'number.gate_relay_auto_off': { state: '0.3' } }, {})
  assert.match(html, /cuts the pulse short/)
})

test('a sensible auto-off, or one that cannot be read, says nothing', () => {
  assert.equal(warnings({ 'number.gate_relay_auto_off': { state: '1.5' } }, {}), '')
  assert.equal(warnings({ 'number.gate_relay_auto_off': { state: 'unavailable' } }, {}), '')
  assert.equal(warnings({}, {}), '')
})

test('both end sensors at their end suggests one is inverted', () => {
  assert.match(warnings({}, { closed: true, open: true }), /probably inverted/)
  assert.equal(warnings({}, { closed: true, open: false }), '')
  assert.match(warnings({}, { closed: true, open: true }, 'es'), /probablemente uno esté invertido/)
})

test('entities the gate was given but Home Assistant does not have are named', () => {
  const html = warnings({ 'switch.porton': { state: 'off' }, 'binary_sensor.gate_open': { state: 'off' } }, {}, 'en', false)
  assert.match(html, /Not found in Home Assistant: sensor\.gate_pm_power, binary_sensor\.gate_closed/)
  assert.doesNotMatch(html, /switch\.porton/)
  assert.match(warnings({ 'switch.porton': { state: 'off' } }, {}, 'es', false), /No se encuentran en Home Assistant/)
})

test('the sensor tiles only report: tapping one never toggles it', async () => {
  const { configs } = await built(ENTITIES)
  for (const entity of ['binary_sensor.gate_closed', 'binary_sensor.gate_open', 'sensor.gate_pm_power', 'switch.porton']) {
    const tile = tiles(configs).find((candidate) => candidate.entity === entity)
    assert.equal(tile.tap_action.action, 'more-info', entity)
    assert.equal(tile.icon_tap_action.action, 'more-info', entity)
  }
})
