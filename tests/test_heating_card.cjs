const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

function load() {
  const window = {
    loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }),
    Annika: { tileConfig: (base, options) => ({ type: 'tile', ...base, ...options }) },
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-heating-card.js'), 'utf8'), {
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
  workday: null,
  day_type: 'workday',
  season: { enabled: true, on_below: 14, off_above: 18, hours: 12, active: true },
  motion_sensors: [{ entity: 'binary_sensor.motion_a', name: 'Kitchen motion' }, { entity: 'binary_sensor.motion_b', name: 'Living motion' }],
  entities: { master: 'switch.annika_heating_enabled' },
  boilers: [{ id: 'boiler', name: 'Boiler', entity: 'switch.heating', zones: ['ground'] }],
  zones: [
    {
      id: 'ground', name: 'Ground Floor', boiler: 'boiler',
      thermostats: [
        { id: 'k', entity: 'climate.kitchen', name: 'Kitchen', icon: null },
        { id: 'l', entity: 'climate.living', name: 'Living', icon: 'mdi:sofa' },
      ],
      schedule: {
        workday: [
          { id: 's1', time: '04:30', name: 'Morning', target: 20, thermostats: [], motion: null },
          { id: 's2', time: '22:00', name: 'Night', target: 16, thermostats: ['climate.kitchen'], motion: { sensors: ['binary_sensor.motion_a'], minutes: 60 } },
        ],
        non_workday: [],
      },
    },
    {
      id: 'patio', name: 'Patio', boiler: 'boiler',
      thermostats: [{ id: 'p', entity: 'climate.patio', name: 'Patio', icon: null }],
      schedule: { workday: [], non_workday: [] },
    },
  ],
}
const state = {
  ground: {
    target: 22, mixed: false, manual: ['climate.living'],
    slot: { id: 's1', name: 'Morning', since: at(-120), conditional: false },
    next: { id: 's2', name: 'Night', time: at(120), target: 16, conditional: true, minutes: 60 },
    plan: [{ time: at(120), name: 'Night', target: 16, conditional: true }],
    thermostats: { 'climate.kitchen': { value: 22, source: 'slot', slot: 's1' }, 'climate.living': { value: 24, source: 'manual', slot: null } },
  },
  patio: { target: null, mixed: false, manual: [], slot: null, next: null, plan: [], thermostats: { 'climate.patio': { value: 'off', source: 'none', slot: null } } },
}
const events = [
  { time: at(-10), kind: 'slot', zone: 'ground', name: 'Morning', target: 22 },
  { time: at(-20), kind: 'manual', zone: 'ground', thermostat: 'climate.living', target: 24, external: true },
  { time: at(-30), kind: 'boiler', boiler: 'boiler', on: true, who: 'Kitchen' },
  { time: at(-40), kind: 'auto', zone: 'ground', thermostat: null },
  { time: at(-50), kind: 'season', on: false, temperature: 19 },
  { time: at(-60), kind: 'master', on: true },
]

function card() {
  const Card = load().AnnikaCards[0][1]
  const el = new Card()
  el._render = () => {}
  el.setConfig({ entity: 'sensor.annika_heating' })
  const climate = (current, target, action = 'idle', mode = 'heat') => ({ state: mode, attributes: { current_temperature: current, temperature: target, hvac_action: action } })
  el._hass = {
    language: 'en',
    calls: [],
    callService(...args) { this.calls.push(args); return Promise.resolve() },
    states: {
      'sensor.annika_heating': { state: 'heating', attributes: { config, state, events } },
      'climate.kitchen': climate(21.8, 22, 'heating'),
      'climate.living': climate(21.9, 24),
      'climate.patio': climate(17, null, 'idle', 'off'),
      'switch.heating': { state: 'on', attributes: {} },
      'weather.home': { state: 'cloudy', attributes: { temperature: 12 } },
    },
    entities: {},
  }
  return el
}

test('registers the card with the ac card as its legacy dependency', () => {
  const entry = load().AnnikaCards[0]
  assert.equal(entry[0], 'annika-heating-card')
  same(entry[2], ['annika-ac-tiles-card'])
})

test('needs an entity or a list of entities', () => {
  const Card = load().AnnikaCards[0][1]
  assert.throws(() => new Card().setConfig({}), /entity/)
})

test('the strip shows the general switch and the boiler', () => {
  const el = card()
  const html = el._stripHtml(config, state, el._texts)
  assert.ok(html.includes('data-master-tile="switch.annika_heating_enabled"') && !html.includes('<ha-switch'))
  assert.ok(html.includes('stile heat') && html.includes('Running · 1 of 2 thermostats heating'))
  const plain = el._stripHtml({ ...config, entities: {} }, state, el._texts)
  assert.ok(plain.includes('heating season (12.0°)') && !plain.includes('data-master-tile'))
  const off = el._stripHtml({ ...config, entities: {}, enabled: false }, state, el._texts)
  assert.ok(off.includes('nothing is automated'))
})

test('a zone shows its target, why, what is next and the manual count', () => {
  const el = card()
  const html = el._zoneHtml(config, config.zones[0], el._zoneInfo(config, state, config.zones[0]), el._texts, false)
  assert.ok(html.includes('22.0<small>°C</small>'))
  assert.ok(html.includes('Morning') && html.includes('22.0° since'))
  assert.ok(html.includes('Night') && html.includes('if no motion for 1 h'))
  assert.ok(html.includes('1 manual') && html.includes('data-zone-auto="ground"'))
  assert.ok(html.includes('Now <b>21.9°</b> average · 1 of 2 heating'))
  assert.ok(html.includes('data-chart="ground|zone"') && html.includes('data-chart="ground|rooms"'))
})

test('a zone with nothing set is off and invites a target', () => {
  const el = card()
  const html = el._zoneHtml(config, config.zones[1], el._zoneInfo(config, state, config.zones[1]), el._texts, false)
  assert.ok(html.includes('bigtemp off') && html.includes('Set a target to turn it on'))
  assert.ok(!html.includes('data-chart='), 'one thermostat: nothing to tell apart')
})

test('a thermostat tile has its gear, its stepper and Auto only when it is manual', () => {
  const el = card()
  const info = el._zoneInfo(config, state, config.zones[0])
  const living = el._roomHtml(config, config.zones[0], config.zones[0].thermostats[1], info, 2, el._texts)
  assert.ok(living.includes('room  override') || living.includes('override'))
  assert.ok(living.includes('data-th-auto="climate.living"') && living.includes('24.0°') && living.includes('data-gear="climate.living"') && living.includes('mdi:sofa'))
  const kitchen = el._roomHtml(config, config.zones[0], config.zones[0].thermostats[0], info, 2, el._texts)
  assert.ok(!kitchen.includes('data-th-auto') && kitchen.includes('Heating'))
})

test('steppers hold a target, and turn off below the minimum', () => {
  const el = card()
  el._holdZone('ground', 1)
  same(el._hass.calls.at(-1), ['annika', 'set_heating_manual', { entity_id: 'sensor.annika_heating', zone: 'ground', target: 22.5 }])
  el._holdThermostat('climate.living', -1)
  same(el._hass.calls.at(-1)[2], { entity_id: 'sensor.annika_heating', thermostats: ['climate.living'], target: 23.5 })
  el._holdZone('patio', 1)
  same(el._hass.calls.at(-1)[2], { entity_id: 'sensor.annika_heating', zone: 'patio', target: 20 })
  const before = el._hass.calls.length
  el._holdZone('patio', -1)
  assert.equal(el._hass.calls.length, before, 'already off')
  assert.equal(el._stepped(5, -1), null)
  assert.equal(el._stepped(35, 1), 35)
})

test('the schedule: bar, rows, conditions and rooms', () => {
  const el = card()
  const html = el._scheduleHtml(config, el._texts)
  assert.ok(html.includes('data-sched-zone="patio"') && html.includes('Workday') && html.includes('Today is a workday'))
  assert.ok(html.includes('value="04:30"') && html.includes('value="Morning"'))
  assert.ok(html.includes('no motion in') && html.includes('Kitchen motion') && html.includes('value="60"') && html.includes('data-slot-minutes="s2"'))
  assert.ok(html.includes('data-slot-addcond="s1"') && html.includes('All rooms') && html.includes('>Kitchen</button>'))
  assert.ok(html.includes('class="seg cond"') && html.includes('nowline'))
  assert.ok(el._barHtml([], true, el._texts).includes('Off'))
})

test('editing a slot sends the whole list of the selected day', async () => {
  const el = card()
  await el._editSlot('s1', (slot) => { slot.target = 21 })
  const call = el._hass.calls.at(-1)
  assert.equal(call[1], 'set_heating_schedule')
  assert.equal(call[2].zone, 'ground')
  assert.equal(call[2].day, 'workday')
  same(call[2].slots.map((slot) => slot.target), [21, 16])
  el._addSlot()
  const added = el._hass.calls.at(-1)[2].slots
  assert.equal(added.length, 3)
  same(added[2], { time: '12:00', name: '', target: 20, thermostats: [], motion: null })
  el._editSlots((slots) => slots.filter((slot) => slot.id !== 's2'))
  same(el._hass.calls.at(-1)[2].slots.map((slot) => slot.id), ['s1'])
})

test('the other day type and zone are edited when chosen', async () => {
  const el = card()
  el._sched = { zone: 'patio', day: 'non_workday' }
  el._addSlot()
  const call = el._hass.calls.at(-1)[2]
  assert.equal(call.zone, 'patio')
  assert.equal(call.day, 'non_workday')
})

test('the popovers list the rooms and the motion sensors', () => {
  const el = card()
  el._pop = { kind: 'rooms', slot: 's2' }
  const rooms = el._popoverHtml(config, el._texts)
  assert.ok(rooms.includes('data-pop-room="climate.kitchen"') && rooms.includes('checked') && rooms.includes('Living'))
  assert.equal((rooms.match(/ checked/g) || []).length, 1, 'only the kitchen')
  el._pop = { kind: 'sensors', slot: 's2' }
  const sensors = el._popoverHtml(config, el._texts)
  assert.ok(sensors.includes('Kitchen motion') && sensors.includes('Living motion') && (sensors.match(/ checked/g) || []).length === 1)
  el._pop = null
  assert.equal(el._popoverHtml(config, el._texts), '')
})

test('the heating season is edited in place', () => {
  const el = card()
  const html = el._automationsHtml(config, el._texts)
  assert.ok(html.includes('data-season="on_below"') && html.includes('value="14"') && html.includes('data-season="off_above"') && html.includes('in season'))
  const none = el._automationsHtml({ ...config, weather: null }, el._texts)
  assert.ok(none.includes('always in season') && !none.includes('data-season='))
})

test('the activity tells each kind of event', () => {
  const el = card()
  const html = el._activityHtml(config, events, el._texts)
  for (const text of [
    'Ground Floor → 22.0° · Morning', 'Living set to 24.0° on the thermostat · manual until Auto', 'Boiler on · Kitchen started heating',
    'Ground Floor back to Auto', 'Heating season ended (19.0°)', 'Heating switched on',
  ]) assert.ok(html.includes(text), text)
  assert.ok(el._activityHtml(config, [], el._texts).includes('Nothing has happened yet'))
})

test('history is parsed with attributes carried forward', () => {
  const el = card()
  const points = el._parseHistory([
    { s: 'heat', a: { current_temperature: 19, temperature: 20 }, lu: 1000 },
    { s: 'heat', a: { current_temperature: 19.5 }, lu: 2000 },
    { s: 'off', lu: 3000 },
  ], 0)
  same(points, [{ t: 1000000, cur: 19, target: 20 }, { t: 2000000, cur: 19.5, target: 20 }, { t: 3000000, cur: 19.5, target: null }])
})

test('the chart draws the zone, or each room', () => {
  const el = card()
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const t0 = start.getTime()
  el._history = {
    'climate.kitchen': [{ t: t0, cur: 19, target: 20 }, { t: t0 + 3600000, cur: 20, target: 22 }],
    'climate.living': [{ t: t0, cur: 18, target: 20 }],
  }
  const info = el._zoneInfo(config, state, config.zones[0])
  const zone = el._chartHtml(config, config.zones[0], info, 'zone', el._texts)
  assert.ok(zone.includes('<svg') && zone.includes('stroke-dasharray="5 4"') && zone.includes('var(--primary-color'))
  const rooms = el._chartHtml(config, config.zones[0], info, 'rooms', el._texts)
  assert.equal((rooms.match(/stroke-linejoin/g) || []).length >= 2, true)
  assert.ok(el._legendHtml(config.zones[0], 'rooms', info, el._texts).includes('Kitchen'))
  assert.ok(el._legendHtml(config.zones[0], 'zone', info, el._texts).includes('Temperature'))
})

test('the settings of a thermostat are its device entities', () => {
  const el = card()
  el._hass.entities = { 'climate.kitchen': { device_id: 'd' }, 'sensor.kitchen_battery': { device_id: 'd' }, 'switch.kitchen_lock': { device_id: 'd' } }
  el._hass.states['sensor.kitchen_battery'] = { state: '80', attributes: { friendly_name: 'Kitchen Battery' } }
  el._hass.states['switch.kitchen_lock'] = { state: 'off', attributes: { friendly_name: 'Kitchen Child lock' } }
  same(el._settingEntities('climate.kitchen'), ['switch.kitchen_lock', 'sensor.kitchen_battery'])
})

test('spanish', () => {
  const el = card()
  el._hass.language = 'es'
  assert.ok(el._stripHtml({ ...config, entities: {} }, state, el._texts).includes('Calefacción'))
})

test('the day tabs follow day_mode', () => {
  const el = card()
  el._hass.language = 'en'
  const week = { ...JSON.parse(JSON.stringify(config)), day_mode: 'days', day_keys: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], day_type: 'tuesday' }
  for (const zone of week.zones) zone.schedule = Object.fromEntries(week.day_keys.map((day) => [day, []]))
  const html = el._scheduleHtml(week, el._texts)
  assert.ok(html.includes('data-sched-day="sunday"') && html.includes('>Monday<') && html.includes('Today is tuesday'))
  assert.ok(!html.includes('Non-workday'))
  const weekend = { ...config, day_mode: 'weekend' }
  const text = el._scheduleHtml(weekend, el._texts)
  assert.ok(text.includes('>Mon–Fri<') && text.includes('>Sat–Sun<') && text.includes('Today is Mon–Fri'))
  const sensor = el._scheduleHtml({ ...config, day_mode: 'sensor' }, el._texts)
  assert.ok(sensor.includes('>Workday<') && sensor.includes('>Non-workday<'))
})
