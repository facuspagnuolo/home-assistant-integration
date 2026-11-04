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
      auto: { arm: { enabled: 'switch.auto_arm', time: 'time.auto_arm', mode: 'away', has_sensors: false } },
    },
  }
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
