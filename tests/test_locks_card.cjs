const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

function load() {
  const window = {
    loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }),
    Annika: { tileConfig: (base, options) => ({ type: 'tile', ...base, ...options }) },
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-locks-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value }, prompt: (...args) => globalThis.answer(...args), setTimeout, clearTimeout, setInterval, clearInterval, Intl, Date,
  })
  return window
}

// The card runs in its own context: what it returns is compared by value.
const same = (actual, expected) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected)

const NOW = Date.now()
const iso = (minutes) => new Date(NOW - minutes * 60000).toISOString()
const later = (minutes) => new Date(NOW + minutes * 60000).toISOString()

const config = {
  notification: true,
  slots: 10,
  offset: 200,
  rule: { enabled: true, locks: [], modes: ['away'], available: true },
  modes: ['away', 'night', 'vacation'],
  locks: [
    {
      id: 'front_door', name: 'Front Door', entity: 'lock.front', sensor: 'binary_sensor.front', battery: 'sensor.front_battery',
      settings: { hold: true, close: true, seconds: 30, open: false, open_seconds: 60 },
      entities: {
        hold: 'switch.front_door_hold_to_unlock', close: 'switch.front_door_lock_when_closed', seconds: 'number.front_door_lock_when_closed_after',
        open: 'switch.front_door_notify_when_left_open', open_seconds: 'number.front_door_notify_when_left_open_after',
      },
    },
    {
      id: 'kitchen', name: 'Kitchen', entity: 'lock.kitchen', sensor: null, battery: null,
      settings: { hold: false, close: false, seconds: 30, open: false, open_seconds: 60 },
      entities: { hold: null, close: null, seconds: null, open: null, open_seconds: null },
    },
  ],
}
const codes = [
  { id: 'a1', slot: 1, name: 'Facu', type: 'fixed', code: '482915', locks: ['front_door', 'kitchen'], expires: null },
  { id: 'b2', slot: 2, name: 'Plumber', type: 'temporary', code: '286641', locks: ['kitchen'], expires: later(26) },
]
const events = [
  { time: iso(1), lock: 'front_door', kind: 'unlock', how: 'keypad', who: 'Delfi', slot: 2, disarmed: true },
  { time: iso(30), lock: 'kitchen', kind: 'emergency', how: 'keypad', who: 'Facu', slot: 201, notified: true },
  { time: iso(40), lock: 'front_door', kind: 'unknown', how: 'keypad', who: null, slot: 4 },
  { time: iso(50), lock: 'kitchen', kind: 'lock', how: 'auto', who: null },
  { time: iso(55), lock: 'front_door', kind: 'left_open', how: 'door', who: null, notified: true },
  { time: iso(60), lock: null, kind: 'expired', how: null, who: 'Guest', slot: 3 },
]

function card(overrides = {}) {
  const Card = load().AnnikaCards[0][1]
  const el = new Card()
  el._render = () => {}
  el.setConfig({ entity: 'sensor.annika_locks' })
  el._hass = {
    language: 'en',
    callService: (...args) => (el.calls ||= []).push(args),
    states: {
      'sensor.annika_locks': { state: iso(1), attributes: { config, codes, events } },
      'lock.front': { state: 'locked', last_changed: iso(1), attributes: {} },
      'lock.kitchen': { state: 'unlocked', last_changed: iso(50), attributes: {} },
      'binary_sensor.front': { state: 'off', attributes: {} },
      'sensor.front_battery': { state: '17', attributes: {} },
      'switch.front_door_hold_to_unlock': { state: 'on', attributes: { friendly_name: 'Front Door Hold to unlock' } },
      'switch.front_door_lock_when_closed': { state: 'off', attributes: { friendly_name: 'Front Door Lock when closed' } },
      'number.front_door_lock_when_closed_after': { state: '30', attributes: { friendly_name: 'Front Door Lock when closed after', mode: 'slider' } },
      'select.front_volume': { state: 'low', attributes: { friendly_name: 'Front Lock Volume' } },
      'switch.front_keypad': { state: 'on', attributes: { friendly_name: 'Front Lock Keypad' } },
      ...overrides.states,
    },
    entities: {
      'lock.front': { device_id: 'dev' },
      'select.front_volume': { device_id: 'dev' },
      'switch.front_keypad': { device_id: 'dev' },
      'sensor.front_battery': { device_id: 'dev' },
      ...overrides.entities,
    },
    devices: { dev: { name: 'Front Lock' } },
  }
  el._events = events
  return el
}

test('registers the card', () => {
  assert.equal(load().AnnikaCards[0][0], 'annika-locks-card')
})

test('a lock tile shows its state, who, the chips and the hold button', () => {
  const el = card()
  const html = el._tileHtml(config, config.locks[0], el._texts, true)
  assert.ok(html.includes('data-state="locked"') && html.includes('Locked'))
  assert.ok(html.includes('Delfi'), 'who moved it, the state change being the logged event')
  assert.ok(html.includes('data-unlock="front_door"') && html.includes('data-hold="1"') && html.includes('Hold to unlock'))
  assert.ok(html.includes('Closed') && html.includes('17%') && html.includes('chip bad'))
  assert.ok(html.includes('data-settings="front_door"'))
  assert.ok(!el._tileHtml(config, config.locks[0], el._texts, false).includes('data-settings='))
})

test('a lock without hold opens with a tap, and an unlocked one offers to lock', () => {
  const el = card()
  const kitchen = el._tileHtml(config, config.locks[1], el._texts, true)
  assert.ok(kitchen.includes('data-state="unlocked"') && kitchen.includes('data-lock="kitchen"') && !kitchen.includes('data-unlock='))
  el._hass.states['lock.kitchen'].state = 'locked'
  const locked = el._tileHtml(config, config.locks[1], el._texts, true)
  assert.ok(locked.includes('data-hold="0"') && locked.includes('>Unlock<'))
  assert.ok(!locked.includes('Closed') && !locked.includes('%'), 'no sensor, no battery: no chips')
})

test('jammed and open-door states', () => {
  const el = card()
  el._hass.states['lock.front'].state = 'jammed'
  assert.ok(el._tileHtml(config, config.locks[0], el._texts, true).includes('The bolt is stuck'))
  el._hass.states['lock.front'].state = 'locked'
  el._hass.states['binary_sensor.front'].state = 'on'
  const html = el._tileHtml(config, config.locks[0], el._texts, true)
  assert.ok(html.includes('Door open') && html.includes('chip warn'))
  el._hass.states['lock.front'].state = 'unavailable'
  assert.ok(!el._tileHtml(config, config.locks[0], el._texts, true).includes('data-unlock='))
})

test('open() and close() call the lock services', () => {
  const el = card()
  el._open('front_door')
  el._close('kitchen')
  same(el.calls, [['lock', 'unlock', { entity_id: 'lock.front' }], ['lock', 'lock', { entity_id: 'lock.kitchen' }]])
})

test('codes hide the code until revealed, then show its emergency variant', () => {
  const el = card()
  let html = el._codesHtml(config, codes, el._texts)
  assert.ok(!html.includes('482915') && !html.includes('482910'))
  assert.ok(html.includes('Slot 1') && html.includes('Fixed') && html.includes('data-until='))
  el._revealed.a1 = true
  html = el._codesHtml(config, codes, el._texts)
  assert.ok(html.includes('482915') && html.includes('482910') && html.includes('Emergency'))
})

test('the codes list is filtered by lock', () => {
  const el = card()
  el._filter = 'front_door'
  const html = el._codesHtml(config, codes, el._texts)
  assert.ok(html.includes('Facu') && !html.includes('Plumber') && html.includes('1 code<'))
})

test('the form validates the code like the integration does', () => {
  const el = card()
  const t = el._texts
  assert.equal(el._codeError(config, '12'), t.err_digits)
  assert.equal(el._codeError(config, '123450'), t.err_zero)
  assert.equal(el._codeError(config, '482915'), t.err_close)
  assert.equal(el._codeError(config, '482910'), t.err_zero)
  assert.equal(el._codeError(config, '482916'), t.err_close, 'its emergency variant would be the same as 482915\'s')
  assert.equal(el._codeError(config, '654321'), '')
})

test('random codes are valid and never end in 0', () => {
  const el = card()
  for (let n = 0; n < 200; n += 1) {
    el.setConfig({ entity: 'sensor.annika_locks' })
    const code = el._form.code
    assert.match(code, /^\d{6}$/)
    assert.ok(!code.endsWith('0'))
  }
})

test('creating a code sends the chosen locks as entities and resets the form', async () => {
  const el = card()
  el._drawForm = () => {}
  el._form = { ...el._form, name: ' Guest ', code: '654321', type: 'fixed', locks: ['kitchen'] }
  assert.equal(el._canCreate(config), true)
  await el._create(config)
  same(el.calls[0], ['annika', 'add_lock_code', { entity_id: 'sensor.annika_locks', name: 'Guest', type: 'fixed', code: '654321', locks: ['lock.kitchen'] }])
  assert.equal(el._form.name, '')
  assert.equal(el._form.locks, null)
})

test('a temporary code goes by hours, or until a moment when one is chosen', async () => {
  const el = card()
  el._drawForm = () => {}
  el._form = { ...el._form, name: 'Plumber', code: '654321', type: 'temporary', hours: 6, until: '' }
  await el._create(config)
  same(el.calls[0][2], { entity_id: 'sensor.annika_locks', name: 'Plumber', type: 'temporary', code: '654321', locks: ['lock.front', 'lock.kitchen'], hours: 6 })
  el._form = { ...el._form, name: 'Plumber', code: '654321', type: 'temporary', until: '2026-12-01T10:00' }
  await el._create(config)
  assert.equal(el.calls[1][2].until, '2026-12-01T10:00')
  assert.equal(el.calls[1][2].hours, undefined)
})

test('a refused code keeps the form and says why', async () => {
  const el = card()
  el._drawForm = () => {}
  el._hass.callService = async () => { throw new Error('No free slot') }
  el._form = { ...el._form, name: 'Guest', code: '654321' }
  await el._create(config)
  assert.equal(el._form.error, 'No free slot')
  assert.equal(el._form.name, 'Guest')
  assert.equal(el._form.busy, false)
})

test('the form cannot be created without a name, a lock or a good code', () => {
  const el = card()
  el._form = { ...el._form, name: '', code: '654321' }
  assert.equal(el._canCreate(config), false)
  el._form = { ...el._form, name: 'A', code: '654320' }
  assert.equal(el._canCreate(config), false)
  el._form = { ...el._form, name: 'A', code: '654321', locks: [] }
  assert.equal(el._canCreate(config), false)
})

test('the form is not drawn with a "works on" row for a single lock', () => {
  const el = card()
  const one = { ...config, locks: [config.locks[0]] }
  assert.ok(!el._formHtml(one, el._texts).includes('data-flock'))
  assert.ok(el._formHtml(config, el._texts).includes('data-flock="kitchen"'))
})

test('automations: one pill per lock and mode, any mode, and no notify checkbox', () => {
  const el = card()
  const html = el._automationsHtml(config, el._texts)
  same([...html.matchAll(/data-rlock="(\w+)"/g)].map((m) => m[1]), ['front_door', 'kitchen'])
  same([...html.matchAll(/data-rmode="(\w+)"/g)].map((m) => m[1]), ['away', 'night', 'vacation'])
  assert.ok(html.includes('data-rany') && html.includes('data-rtest') && !html.includes('data-rnotify'))
  assert.ok(html.includes('data-rmode="away" ') || html.includes('pill small sel" data-rmode="away"'))
  assert.ok(!html.includes('Unlocked with'))
})

test('the rule is edited through the service, the locks as entities', () => {
  const el = card()
  el._setLocks(config, 'kitchen')
  same(el.calls.pop()[2], { entity_id: 'sensor.annika_locks', locks: ['lock.front'] })
  el._setLocks({ ...config, rule: { ...config.rule, locks: ['front_door'] } }, 'kitchen')
  same(el.calls.pop()[2].locks, [], 'every lock is the empty list')
  el._setLocks({ ...config, rule: { ...config.rule, locks: ['front_door'] } }, 'front_door')
  assert.equal(el.calls.length, 0, 'the last lock cannot be turned off')
  el._setModes(config, 'night')
  same(el.calls.pop()[2].modes, ['away', 'night'])
  el._setModes(config, 'away')
  same(el.calls.pop()[2].modes, [])
})

test('the rule says when there is no alarm', () => {
  const el = card()
  const html = el._automationsHtml({ ...config, rule: { ...config.rule, available: false } }, el._texts)
  assert.ok(html.includes('not set up') && html.includes('data-ron') && html.includes('disabled'))
})

test('activity says who, how, and what happened to the alarm', () => {
  const el = card()
  const html = el._activityHtml(config, events, el._texts)
  assert.ok(html.includes('<b>Delfi</b><span class="via">unlocked with a code</span>'))
  assert.ok(html.includes('Alarm disarmed') && !html.includes('· notification sent'))
  assert.ok(html.includes('entered the emergency code') && html.includes('Security notification sent') && html.includes('extra bad'))
  assert.ok(html.includes('Unknown code 4'))
  assert.ok(html.includes('<b>Auto-lock</b><span class="via">locked itself</span>'))
  assert.ok(html.includes('<b>Guest</b>') && html.includes('expired and was removed'))
  assert.ok(html.includes('Today'))
})

test('activity in Spanish', () => {
  const el = card()
  el._hass.language = 'es'
  const html = el._activityHtml(config, events, el._texts)
  assert.ok(html.includes('abrió con un código') && html.includes('Alarma desactivada') && html.includes('Hoy'))
  assert.ok(html.includes('Código desconocido 4'))
})

test('settings: the hold switch first, then the device, then the door and battery; the rules are not here', () => {
  const el = card()
  const ids = el._settingEntities(config.locks[0])
  assert.equal(ids[0], 'switch.front_door_hold_to_unlock')
  assert.ok(!ids.some((id) => /lock_when_closed|left_open/.test(id)), 'lock when closed and notify when open are in the Automations')
  assert.ok(ids.indexOf('switch.front_keypad') < ids.indexOf('select.front_volume'))
  assert.ok(!ids.includes('lock.front'))
  assert.equal(ids.filter((id) => id === 'sensor.front_battery').length, 1, 'the battery is not listed twice')
  assert.equal(ids[ids.length - 1], 'binary_sensor.front', 'the door sensor is added when its device does not have it')
})

test('settings tiles are native tile cards with the one feature their kind needs', () => {
  const el = card()
  const lock = config.locks[0]
  const volume = el._settingTile('select.front_volume', lock)
  assert.equal(volume.type, 'tile')
  same(volume.features, [{ type: 'select-options' }])
  assert.equal(volume.name, 'Volume')
  const seconds = el._settingTile('number.front_door_lock_when_closed_after', lock)
  same(seconds.features, [{ type: 'numeric-input', style: 'slider' }])
  same(el._settingTile('switch.front_door_hold_to_unlock', lock).features, [])
  assert.equal(el._settingTile('binary_sensor.front', lock).name, 'Door sensor')
  assert.equal(el._settingTile('sensor.front_battery', lock).name, 'Battery')
})

test('the settings page has the lock tile without a gear, a back button and a place for the tiles', () => {
  const el = card()
  el._settings = 'front_door'
  const html = el._settingsHtml(config, el._texts)
  assert.ok(html.includes('data-back') && html.includes('data-settings-tiles') && html.includes('Front Door · Settings'))
  assert.ok(!html.includes('data-settings="front_door"'))
  assert.ok(!html.includes('Unlocking from the dashboard'))
})

test('the settings tiles are mounted once and reused', async () => {
  const el = card()
  el._settings = 'front_door'
  const placed = []
  el.querySelector = () => ({ replaceChildren: (...children) => placed.push(children) })
  global.window = undefined
  await el._mountSettings(config)
  const first = placed[0]
  await el._mountSettings(config)
  assert.equal(first.length, 5)
  assert.ok(first.every((child, at) => child === placed[1][at]))
})

test('relative times and time left', () => {
  const el = card()
  assert.equal(el._left(later(26)), '26 min')
  assert.equal(el._left(later(200)), '3 h 20 min')
  assert.equal(el._left(later(60 * 72)), '3 d')
  assert.equal(el._ago(iso(0)), 'just now')
  assert.match(el._ago(iso(5)), /5/)
})

test('the settings are one table: a column per lock, a row per setting', () => {
  const el = card()
  const html = el._settingsTableHtml(config, el._texts)
  assert.ok(html.includes('data-heading="Settings"'))
  assert.deepEqual([...html.matchAll(/<th>([^<]+)<\/th>/g)].map((m) => m[1]), ['Front Door', 'Kitchen'])
  assert.equal((html.match(/<tr>/g) || []).length, 3, 'the header and the two settings')
  assert.ok(html.includes('Lock after closing') && html.includes('Notify when left open'))
  assert.ok(html.includes('data-lswitch="switch.front_door_lock_when_closed" checked'))
  assert.ok(html.includes('data-lnumber="number.front_door_lock_when_closed_after"') && html.includes('value="30"'))
  assert.ok(html.includes('data-lswitch="switch.front_door_notify_when_left_open"') && !html.includes('data-lswitch="switch.front_door_notify_when_left_open" checked'))
  assert.ok(html.includes('data-lnumber="number.front_door_notify_when_left_open_after"') && html.includes('value="60"'))
})

test('a lock without a door sensor has its cells turned off', () => {
  const el = card()
  const html = el._settingsTableHtml(config, el._texts)
  assert.equal((html.match(/cell off/g) || []).length, 2)
  assert.ok(html.includes('Needs a door sensor'))
})

test('the settings ask for a notify_view when there is none, and are not in the automations', () => {
  const el = card()
  assert.ok(!el._settingsTableHtml(config, el._texts).includes('notify_view'))
  assert.ok(el._settingsTableHtml({ ...config, notification: false }, el._texts).includes('notify_view'))
  assert.ok(!el._automationsHtml(config, el._texts).includes('data-lswitch'))
})

test('the switches and seconds call their entities', () => {
  const el = card()
  const handlers = {}
  el.querySelectorAll = (selector) => (['[data-lswitch]', '[data-lnumber]'].includes(selector)
    ? [{ dataset: { lswitch: 'switch.a', lnumber: 'number.b' }, checked: true, value: '45', addEventListener: (_event, fn) => (handlers[selector] = fn) }]
    : [])
  el._bind(config)
  handlers['[data-lswitch]']()
  handlers['[data-lnumber]']()
  same(el.calls, [['switch', 'turn_on', { entity_id: 'switch.a' }], ['number', 'set_value', { entity_id: 'number.b', value: 45 }]])
})

test('activity tells a door left open', () => {
  const el = card()
  const html = el._activityHtml(config, events, el._texts)
  assert.ok(html.includes('<b>Front Door</b><span class="via">was left open</span>') && html.includes('Notification sent'))
})

test('the codes table offers to import from the locks and to rename a code', () => {
  const el = card()
  const html = el._codesHtml(config, codes, el._texts)
  assert.match(html, /data-import/)
  assert.match(html, /Import from locks/)
  assert.match(html, /data-rename="a1"/)
})

test('importing and renaming call their services', async () => {
  const el = card()
  el._say = (message) => (el.said = message)
  el._service = async (service, data) => (el.calls ||= []).push([service, data])
  globalThis.answer = () => '  Mamá '
  await el._rename('a1')
  await el._import()
  same(el.calls, [['rename_lock_code', { id: 'a1', name: 'Mamá' }], ['import_lock_codes', {}]])
  assert.equal(el.said, 'No new codes found in the locks.')
  delete globalThis.answer
})
