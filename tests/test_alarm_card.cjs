const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

const ENTITY = 'alarm_control_panel.alarma'

function panel(state = 'disarmed') {
  return {
    state,
    attributes: {
      friendly_name: 'Alarma',
      mode: null,
      locked_until: null,
      deadline: null,
      modes: {
        away: { enabled: true, arming: 30, pending: 20 },
        night: { enabled: true, arming: 0, pending: 10 },
      },
      config: {
        warning: { limit: 3, window_minutes: 10, count: 1, confirm: null },
        outputs: [{ id: 'siren', name: 'Sirena', entities: ['switch.sirena'], warning_enabled: true, warning_seconds: 30, trigger_enabled: true, on: false }],
        notification: { enabled: true, view: 'alarma', warning: true, trigger: true, trigger_repeat: 0 },
        zones: [{ id: 'planta_baja', name: 'Planta baja', rules: { away: 'trigger', night: 'off' }, sensors: [{ id: 'cocina', name: 'Cocina', detail: '', entities: [], rules: { away: null, night: null } }] }],
      },
      decisions: [{ level: 'trigger', text: 'Se disparó por Cocina', time: new Date().toISOString() }],
      auto: { arm: { enabled: 'switch.auto_arm', time: 'time.auto_arm', mode: 'away', has_sensors: false, sensors: [], sensor_options: [] } },
    },
  }
}

const OPTIONS = [
  { entity: 'binary_sensor.cocina', name: 'Cocina' },
  { entity: 'binary_sensor.living', name: 'Living' },
  { entity: 'binary_sensor.patio', name: 'Patio' },
]

function withSensors(sensors) {
  const state = panel()
  Object.assign(state.attributes.auto.arm, { has_sensors: sensors.length > 0, quiet_minutes: 'number.quiet', sensors, sensor_options: OPTIONS })
  return state
}

function render(config, state) {
  class Element {
    constructor() {
      this.innerHTML = ''
      this.style = {}
      this.offsetHeight = 0
    }
    querySelectorAll() { return [] }
    querySelector() { return null }
  }
  const window = {}
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-alarm-card.js'), 'utf8'), {
    window,
    HTMLElement: Element,
    requestAnimationFrame: (fn) => fn(),
  })
  const Card = window.AnnikaCards.find(([name]) => name === 'annika-alarm-card')[1]
  const card = new Card()
  card._hass = { language: 'es', states: { [ENTITY]: state } }
  card.setConfig({ entity: ENTITY, ...config })
  return card
}

test('by default the card draws the whole alarm', () => {
  const html = render({}, panel()).innerHTML
  for (const part of ['data-change', 'data-warning', 'data-out-trigger', 'data-timing', 'data-zone', 'data-switch', 'class="decision"']) {
    assert.ok(html.includes(part), `missing ${part}`)
  }
})

test('view_only keeps the keypad and the activity and nothing else', () => {
  const html = render({ view_only: true }, panel()).innerHTML
  assert.ok(html.includes('data-key="1"'))
  assert.ok(html.includes('data-mode="arm_away"'))
  assert.ok(html.includes('class="decision"'))
  assert.ok(html.includes('Se disparó por Cocina'))
  for (const part of ['data-change', 'data-cancel', 'data-warning', 'data-out-warning', 'data-out-trigger', 'data-duration', 'data-notify', 'data-mode-enabled', 'data-timing', 'data-test', 'data-zone', 'data-sensor', 'data-select', 'data-switch', 'data-time=', 'data-number']) {
    assert.ok(!html.includes(part), `view_only still draws ${part}`)
  }
})

test('view_only still asks for the code to disarm while the alarm is armed', () => {
  const html = render({ view_only: true }, panel('armed_away')).innerHTML
  assert.ok(html.includes('Ingresá el código para desarmar'))
  assert.ok(!html.includes('data-change'))
})

test('only a literal true turns view_only on', () => {
  for (const value of ['true', 1, 'yes']) {
    assert.ok(render({ view_only: value }, panel()).innerHTML.includes('data-change'), String(value))
  }
})

test('view_only cannot start a code change', () => {
  const card = render({ view_only: true }, panel())
  card._startChange()
  assert.equal(card._change, null)
})

test('without sensors the arming waits for none: a dropdown to choose them, and no minutes', () => {
  const html = render({}, withSensors([])).innerHTML
  assert.ok(html.includes('data-auto-sensors'))
  assert.ok(html.includes('Sin esperar sensores'))
  assert.ok(!html.includes('data-number'))
})

test('with sensors the dropdown names them and the quiet minutes come back', () => {
  const html = render({}, withSensors(['binary_sensor.cocina', 'binary_sensor.living'])).innerHTML
  assert.ok(html.includes('cuando ninguno de'))
  assert.ok(html.includes('>Cocina, Living</button>'))
  assert.ok(html.includes('data-number="number.quiet"'))
  const many = render({}, withSensors(['binary_sensor.cocina', 'binary_sensor.living', 'binary_sensor.patio'])).innerHTML
  assert.ok(many.includes('3 sensores de movimiento'))
})

test('the dropdown opens a list with every sensor and the chosen ones checked', () => {
  const card = render({}, withSensors(['binary_sensor.living']))
  assert.ok(!card.innerHTML.includes('data-popover'))
  card._sensorsOpen = true
  card._render(true)
  const html = card.innerHTML
  assert.ok(html.includes('data-popover'))
  for (const entity of OPTIONS.map((item) => item.entity)) assert.ok(html.includes(`data-pop-sensor="${entity}"`), entity)
  assert.ok(/data-pop-sensor="binary_sensor.living" checked/.test(html))
  assert.ok(!/data-pop-sensor="binary_sensor.cocina" checked/.test(html))
})

test('a chosen sensor that is no longer offered stays in the list, with a readable name', () => {
  const card = render({}, withSensors(['binary_sensor.gone_away']))
  card._sensorsOpen = true
  card._render(true)
  assert.ok(/data-pop-sensor="binary_sensor.gone_away" checked/.test(card.innerHTML))
  assert.ok(card.innerHTML.includes('> Gone Away</label>'))
})

test('the list shows names, never entity ids, and the name Home Assistant has now', () => {
  const state = withSensors(['binary_sensor.rp_person'])
  state.attributes.auto.arm.sensor_options = [
    { entity: 'binary_sensor.rp_person', name: 'Rp Person', group: 'Camara 1' },
    { entity: 'binary_sensor.rp_vehicle', name: 'Rp Vehicle', group: 'Camara 1' },
    { entity: 'binary_sensor.patio', name: 'Patio' },
  ]
  const card = render({}, state)
  card._hass.states['binary_sensor.rp_person'] = { state: 'off', attributes: { friendly_name: 'RP-PCB8M Person' } }
  card._sensorsOpen = true
  card._render(true)
  const html = card.innerHTML
  assert.ok(html.includes('Camara 1 · RP-PCB8M Person'))
  assert.ok(html.includes('Camara 1 · Rp Vehicle'))
  assert.ok(html.includes('> Patio</label>'))
  assert.ok(!/>[^<]*binary_sensor\.[^<]*</.test(html.replace(/data-[a-z-]+="[^"]*"/g, '')), 'an entity id is shown')
})

test('the list is asked for, so it has what Home Assistant has now, and again when it opens', async () => {
  const calls = []
  const card = render({}, withSensors(['binary_sensor.cocina']))
  card._hass.callWS = async (message) => {
    calls.push(message.type)
    return [{ entity: 'binary_sensor.cocina', name: 'Cocina' }, { entity: 'binary_sensor.rp_motion', name: 'RP-PCB8M Motion' }]
  }
  card._render(true)
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(calls, ['annika/alarm_sensor_options'])
  card._sensorsOpen = true
  card._render(true)
  assert.ok(card.innerHTML.includes('data-pop-sensor="binary_sensor.rp_motion"'))
  assert.ok(!card.innerHTML.includes('data-pop-sensor="binary_sensor.patio"'))
})

test('if the list cannot be asked for, the card keeps drawing and does not insist', async () => {
  let calls = 0
  const card = render({}, withSensors(['binary_sensor.cocina']))
  card._hass.callWS = async () => { calls += 1; throw new Error('unknown command') }
  card._render(true)
  await new Promise((resolve) => setImmediate(resolve))
  card._render(true)
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(calls, 1)
  assert.ok(card.innerHTML.includes('Cocina'))
})

test('view_only never draws the sensors list', () => {
  const card = render({ view_only: true }, withSensors(['binary_sensor.living']))
  card._sensorsOpen = true
  card._render(true)
  assert.ok(!card.innerHTML.includes('data-popover'))
  assert.ok(!card.innerHTML.includes('data-auto-sensors'))
})

test('in Spanish the mode buttons say only the name of the mode', () => {
  const html = render({}, panel()).innerHTML
  assert.ok(html.includes('data-mode="arm_away">Salida</button>'))
  assert.ok(html.includes('data-mode="arm_night">Noche</button>'))
  const modes = html.slice(html.indexOf('class="modes"'), html.indexOf('</div>', html.indexOf('class="modes"')))
  assert.ok(!modes.includes('Armar'), 'no "Armar" in the mode buttons')
})

test('the prompt is above the modes, not below', () => {
  const html = render({}, panel()).innerHTML
  const prompt = html.indexOf('class="prompt"')
  assert.ok(prompt > 0 && prompt < html.indexOf('class="modes"'), 'the prompt comes first')
  assert.ok(html.includes('Elegí un modo'))
})

test('view_only does not offer to change the code, nor while armed', () => {
  for (const state of ['disarmed', 'armed_night']) {
    const html = render({ view_only: true }, panel(state)).innerHTML
    assert.ok(!html.includes('Cambiar código') && !html.includes('data-change'), state)
  }
})
