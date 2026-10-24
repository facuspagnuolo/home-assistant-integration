const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

function load() {
  const window = {
    loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }),
    Annika: { tileConfig: (base, options) => ({ type: 'tile', ...base, ...options }) },
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-ac-card.js'), 'utf8'), {
    window, HTMLElement: class {}, customElements: { get: () => null }, setTimeout, clearTimeout, setInterval, clearInterval, Intl, Date,
  })
  return window
}

const same = (actual, expected) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected)

const NOW = new Date()
const at = (minutes) => new Date(NOW.getTime() + minutes * 60000).toISOString()

const config = {
  enabled: true,
  weather: 'weather.home',
  day_mode: 'sensor',
  day_keys: ['workday', 'non_workday'],
  day_type: 'workday',
  season: { enabled: true, on_above: 26, off_below: 22, hours: 12, active: true },
  entities: { master: 'switch.annika_ac_enabled' },
  zones: [
    {
      id: 'first', name: 'First Floor',
      units: [
        { id: 'm', entity: 'climate.main', name: 'Main Bedroom', icon: null },
        { id: 'k', entity: 'climate.kids', name: 'Kids', icon: 'mdi:bed' },
      ],
      schedule: {
        workday: [
          { id: 's1', time: '07:00', name: 'Day', mode: 'off', target: null, fan: null, units: [] },
          { id: 's2', time: '21:30', name: 'Night', mode: 'cool', target: 24, fan: 'low', units: ['climate.main'] },
        ],
        non_workday: [],
      },
    },
    {
      id: 'ground', name: 'Ground Floor',
      units: [{ id: 'o', entity: 'climate.office', name: 'Office', icon: null }],
      schedule: { workday: [], non_workday: [] },
    },
  ],
}
const state = {
  first: {
    target: 24, manual: ['climate.kids'],
    slot: { id: 's2', name: 'Night', since: at(-120), mode: 'cool', target: 24 },
    next: { id: 's1', name: 'Day', time: at(120), mode: 'off', target: null },
    plan: [{ time: at(120), name: 'Day', mode: 'off', target: null }],
    units: {
      'climate.main': { mode: 'cool', target: 24, fan: 'low', source: 'slot', slot: 's2' },
      'climate.kids': { mode: 'cool', target: 23, fan: 'high', source: 'manual', slot: null },
    },
  },
  ground: { target: null, manual: [], slot: null, next: null, plan: [], units: { 'climate.office': { mode: 'off', target: null, fan: null, source: 'none', slot: null } } },
}
const events = [
  { time: at(-10), kind: 'slot', zone: 'first', name: 'Night', mode: 'cool', target: 24 },
  { time: at(-20), kind: 'manual', zone: 'first', unit: 'climate.kids', mode: 'cool', target: 23, fan: null, external: false },
  { time: at(-30), kind: 'manual', zone: 'first', unit: 'climate.main', mode: 'heat', target: 21, fan: null, external: true },
  { time: at(-40), kind: 'auto', zone: 'first', unit: null },
  { time: at(-50), kind: 'season', on: false, temperature: 19 },
  { time: at(-60), kind: 'master', on: true },
]

function card() {
  const Card = load().AnnikaCards[0][1]
  const el = new Card()
  el._render = () => {}
  el.setConfig({ entity: 'sensor.annika_ac' })
  const unit = (mode, current, target, action = 'idle', extra = {}) => ({
    state: mode,
    attributes: {
      current_temperature: current, temperature: target, hvac_action: action, hvac_modes: ['off', 'fan_only', 'dry', 'cool', 'heat', 'auto'],
      fan_modes: ['auto', 'low', 'medium', 'high'], fan_mode: 'low', swing_modes: ['off', 'vertical'], swing_mode: 'off',
      swing_horizontal_modes: ['off', 'on'], swing_horizontal_mode: 'on', ...extra,
    },
  })
  el._hass = {
    language: 'en',
    calls: [],
    callService(...args) { this.calls.push(args); return Promise.resolve() },
    states: {
      'sensor.annika_ac': { state: 'running', attributes: { config, state, events } },
      'climate.main': unit('cool', 24.5, 24, 'cooling'),
      'climate.kids': unit('cool', 23.5, 23, 'idle', { fan_mode: 'high' }),
      'climate.office': unit('off', 26, null, 'off', { hvac_action: 'off' }),
      'weather.home': { state: 'sunny', attributes: { temperature: 29 } },
    },
    entities: {},
  }
  return el
}

test('registers the card with the tiles card as its legacy dependency', () => {
  const entry = load().AnnikaCards[0]
  assert.equal(entry[0], 'annika-ac-card')
  same(entry[2], ['annika-ac-tiles-card'])
})

test('needs an entity or a list of entities', () => {
  const Card = load().AnnikaCards[0][1]
  assert.throws(() => new Card().setConfig({}), /entity/)
})

test('the strip shows the general switch and how many are running', () => {
  const el = card()
  const infos = config.zones.map((zone) => el._zoneInfo(config, state, zone))
  const html = el._stripHtml(config, state, infos, el._texts)
  assert.ok(html.includes('data-master-tile="switch.annika_ac_enabled"') && !html.includes('<ha-switch'))
  assert.ok(html.includes('1 of 3 running') && html.includes('average 24.7°'))
  const plain = el._stripHtml({ ...config, entities: {} }, state, infos, el._texts)
  assert.ok(plain.includes('cooling season (29.0°)') && !plain.includes('data-master-tile'))
  const off = el._stripHtml({ ...config, entities: {}, enabled: false }, state, infos, el._texts)
  assert.ok(off.includes('nothing is automated'))
})

test('a zone shows its target, why, what is next and the manual count', () => {
  const el = card()
  const html = el._zoneHtml(config, config.zones[0], el._zoneInfo(config, state, config.zones[0]), el._texts)
  assert.ok(html.includes('24.0<small>°C</small>'))
  assert.ok(html.includes('Night') && html.includes('Cool 24.0° since'))
  assert.ok(html.includes('Next: <b>Day</b>') && html.includes('· Off'))
  assert.ok(html.includes('1 manual') && html.includes('data-zone-auto="first"') && html.includes('Cooling season'))
  assert.ok(html.includes('data-chart="first|zone"') && html.includes('data-chart="first|rooms"'))
})

test('a zone with nothing set is off and cannot be lowered', () => {
  const el = card()
  const html = el._zoneHtml(config, config.zones[1], el._zoneInfo(config, state, config.zones[1]), el._texts)
  assert.ok(html.includes('bigtemp off') && html.includes('data-zone-step="ground|-1"') && html.includes('disabled'))
  assert.ok(!html.includes('data-chart='), 'one unit: nothing to tell apart')
})

test('a unit tile has its modes, fan, swing, gear and Auto only when it is manual', () => {
  const el = card()
  const info = el._zoneInfo(config, state, config.zones[0])
  const kids = el._unitHtml(config, config.zones[0], config.zones[0].units[1], info, el._texts)
  assert.ok(kids.includes('override') && kids.includes('data-unit-auto="climate.kids"') && kids.includes('data-gear="climate.kids"') && kids.includes('mdi:bed'))
  for (const mode of ['off', 'fan_only', 'dry', 'cool', 'heat', 'auto']) assert.ok(kids.includes(`data-unit-mode="climate.kids|${mode}"`), mode)
  for (const fan of ['auto', 'low', 'medium', 'high']) assert.ok(kids.includes(`data-unit-fan="climate.kids|${fan}"`), fan)
  assert.ok(kids.includes('data-unit-swing="climate.kids|swing|vertical|vertical"'), 'off, so a tap turns it on')
  assert.ok(kids.includes('data-unit-swing="climate.kids|swing_horizontal|on|off"'), 'on, so a tap turns it off')
  assert.ok(kids.includes('23.0°') && kids.includes('23.5°'))
  const main = el._unitHtml(config, config.zones[0], config.zones[0].units[0], info, el._texts)
  assert.ok(!main.includes('data-unit-auto') && main.includes('Cooling') && main.includes('running'))
  const office = el._unitHtml(config, config.zones[1], config.zones[1].units[0], el._zoneInfo(config, state, config.zones[1]), el._texts)
  assert.ok(office.includes('disabled') && office.includes('—') && /room acu\s+off/.test(office))
})

test('a unit shows only what it can do', () => {
  const el = card()
  el._hass.states['climate.main'].attributes.hvac_modes = ['off', 'cool', 'heat']
  el._hass.states['climate.main'].attributes.fan_modes = ['auto']
  delete el._hass.states['climate.main'].attributes.swing_modes
  delete el._hass.states['climate.main'].attributes.swing_horizontal_modes
  const html = el._unitHtml(config, config.zones[0], config.zones[0].units[0], el._zoneInfo(config, state, config.zones[0]), el._texts)
  assert.ok(!html.includes('|dry"') && html.includes('|heat"') && !html.includes('|medium"') && !html.includes('data-unit-swing'))
})

test('steppers hold a target for a zone or a unit', () => {
  const el = card()
  el._holdZone('first', 1)
  same(el._hass.calls.at(-1), ['annika', 'set_ac_manual', { entity_id: 'sensor.annika_ac', zone: 'first', target: 24.5 }])
  el._holdUnit('climate.kids', -1)
  same(el._hass.calls.at(-1)[2], { entity_id: 'sensor.annika_ac', units: ['climate.kids'], target: 22.5 })
  el._holdZone('ground', 1)
  same(el._hass.calls.at(-1)[2], { entity_id: 'sensor.annika_ac', zone: 'ground', mode: 'cool', target: 24 })
  const before = el._hass.calls.length
  el._holdZone('ground', -1)
  el._holdUnit('climate.office', 1)
  assert.equal(el._hass.calls.length, before, 'off: nothing to lower, no target to step')
  assert.equal(el._next(32, 1), 32)
  assert.equal(el._next(16, -1), 16)
})

test('the schedule: bar and rows', () => {
  const el = card()
  const html = el._scheduleHtml(config, el._texts)
  assert.ok(html.includes('data-sched-zone="ground"') && html.includes('Workday') && html.includes('Today is a workday'))
  assert.ok(html.includes('value="07:00"') && html.includes('value="Night"') && html.includes('data-slot-mode="s2"') && html.includes('data-slot-fan="s2"'))
  assert.ok(html.includes('Cool') && html.includes('24.0°') && html.includes('Low') && html.includes('>Main Bedroom</button>'))
  assert.ok(html.includes('class="seg on"') && html.includes('class="seg none"') && html.includes('nowline'))
  assert.ok(!html.includes('Only if'))
  assert.ok(el._barHtml([], true, el._texts).includes('Off'))
})

test('editing a slot sends the whole list of the selected day', async () => {
  const el = card()
  await el._editSlot('s2', (slot) => { slot.target = 23 })
  const call = el._hass.calls.at(-1)
  assert.equal(call[1], 'set_ac_schedule')
  assert.equal(call[2].zone, 'first')
  assert.equal(call[2].day, 'workday')
  same(call[2].slots.map((slot) => slot.target), [null, 23])
  el._addSlot()
  const added = el._hass.calls.at(-1)[2].slots
  assert.equal(added.length, 3)
  same(added[2], { time: '12:00', name: '', mode: 'cool', target: 24, fan: null, units: [] })
  el._editSlots((slots) => slots.filter((slot) => slot.id !== 's2'))
  same(el._hass.calls.at(-1)[2].slots.map((slot) => slot.id), ['s1'])
})

test('the other day type and zone are edited when chosen', () => {
  const el = card()
  el._sched = { zone: 'ground', day: 'non_workday' }
  el._addSlot()
  const call = el._hass.calls.at(-1)[2]
  assert.equal(call.zone, 'ground')
  assert.equal(call.day, 'non_workday')
})

test('the popovers list the modes, the fans and the rooms', () => {
  const el = card()
  el._pop = { kind: 'mode', slot: 's2' }
  const modes = el._popoverHtml(config, el._texts)
  for (const mode of ['off', 'cool', 'heat', 'dry', 'fan_only', 'auto']) assert.ok(modes.includes(`data-pop-mode="${mode}"`), mode)
  el._pop = { kind: 'fan', slot: 's2' }
  const fans = el._popoverHtml(config, el._texts)
  assert.ok(fans.includes('data-pop-fan=""') && fans.includes('Unchanged') && fans.includes('data-pop-fan="low"'))
  el._pop = { kind: 'units', slot: 's2' }
  const rooms = el._popoverHtml(config, el._texts)
  assert.ok(rooms.includes('data-pop-room="climate.main"') && rooms.includes('Kids'))
  assert.equal((rooms.match(/ checked/g) || []).length, 1, 'only the main bedroom')
  el._pop = null
  assert.equal(el._popoverHtml(config, el._texts), '')
})

test('the cooling season is edited in place', () => {
  const el = card()
  const html = el._automationsHtml(config, el._texts)
  assert.ok(html.includes('data-season="on_above"') && html.includes('value="26"') && html.includes('data-season="off_below"') && html.includes('in season'))
  assert.ok(!html.includes('avatar'))
  const none = el._automationsHtml({ ...config, weather: null }, el._texts)
  assert.ok(none.includes('always in season') && !none.includes('data-season='))
})

test('the activity tells each kind of event', () => {
  const el = card()
  const html = el._activityHtml(config, events, el._texts)
  for (const text of [
    'First Floor → Cool 24.0° · Night', 'Kids set to Cool 23.0° · manual until Auto', 'Main Bedroom changed on the unit (Heat 21.0°)',
    'First Floor back to Auto', 'Cooling season ended (19.0°)', 'AC switched on',
  ]) assert.ok(html.includes(text), text)
  assert.ok(el._activityHtml(config, [], el._texts).includes('Nothing has happened yet'))
})

test('the chart draws the zone, or each room, and the plan breaks where it turns off', () => {
  const el = card()
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const t0 = start.getTime()
  el._history = {
    'climate.main': [{ t: t0, cur: 26, target: null }, { t: t0 + 3600000, cur: 25, target: 24 }],
    'climate.kids': [{ t: t0, cur: 25, target: null }],
  }
  const info = el._zoneInfo(config, state, config.zones[0])
  const zone = el._chartHtml(config, config.zones[0], info, 'zone', el._texts)
  assert.ok(zone.includes('<svg') && zone.includes('stroke-dasharray="5 4"') && zone.includes('var(--primary-color'))
  assert.ok(!zone.includes('NaN'))
  const rooms = el._chartHtml(config, config.zones[0], info, 'rooms', el._texts)
  assert.equal((rooms.match(/stroke-linejoin/g) || []).length >= 2, true)
  assert.ok(el._legendHtml(config.zones[0], 'rooms', info, el._texts).includes('Main Bedroom'))
})

test('the settings of a unit are its device entities', () => {
  const el = card()
  el._hass.entities = { 'climate.main': { device_id: 'd' }, 'sensor.main_filter': { device_id: 'd' }, 'switch.main_beep': { device_id: 'd' } }
  el._hass.states['sensor.main_filter'] = { state: '80', attributes: { friendly_name: 'Main Filter' } }
  el._hass.states['switch.main_beep'] = { state: 'off', attributes: { friendly_name: 'Main Beep' } }
  same(el._settingEntities('climate.main'), ['switch.main_beep', 'sensor.main_filter'])
})

test('spanish', () => {
  const el = card()
  el._hass.language = 'es'
  const infos = config.zones.map((zone) => el._zoneInfo(config, state, zone))
  assert.ok(el._stripHtml({ ...config, entities: {} }, state, infos, el._texts).includes('temporada de AC'))
  assert.equal(el._modeText('cool'), 'Frío')
})

test('the day tabs follow day_mode', () => {
  const el = card()
  const week = { ...JSON.parse(JSON.stringify(config)), day_mode: 'days', day_keys: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], day_type: 'tuesday' }
  for (const zone of week.zones) zone.schedule = Object.fromEntries(week.day_keys.map((day) => [day, []]))
  const html = el._scheduleHtml(week, el._texts)
  assert.ok(html.includes('data-sched-day="sunday"') && html.includes('>Monday<') && html.includes('Today is tuesday'))
  const weekend = { ...config, day_mode: 'weekend' }
  assert.ok(el._scheduleHtml(weekend, el._texts).includes('>Mon–Fri<'))
})
