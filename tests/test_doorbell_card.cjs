const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

function load() {
  const window = {
    loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }),
    Annika: { tileConfig: (base, options) => ({ type: 'tile', ...base, ...options }) },
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-doorbell-card.js'), 'utf8'), {
    window, HTMLElement: class {}, CSS: { escape: (value) => value }, setTimeout, clearTimeout,
  })
  return window
}

const config = {
  notification: true,
  notifications: { devices: { home: true, away: true }, users: { home: false, away: true } },
  presence: {
    home: 0,
    people: [{ entity: 'person.golf', name: 'Golf', home: false }, { entity: 'person.delfi', name: 'Delfi', home: false }],
  },
  talk: { mute_speaker: true, auto_off: true, auto_off_seconds: 60 },
  doorbells: [{ id: 'front', name: 'Front door', entity: 'camera.front', visitor: 'binary_sensor.v', sensors: { person: 'binary_sensor.p' } }],
}

function card() {
  const Card = load().AnnikaCards[0][1]
  const el = new Card()
  el._render = () => {}
  el.setConfig({ entity: 'sensor.annika_doorbells' })
  el._hass = {
    language: 'en',
    states: {
      'sensor.annika_doorbells': { attributes: { config } },
      'person.golf': { state: 'not_home', attributes: { friendly_name: 'Golf', device_trackers: ['device_tracker.a'] } },
      'person.delfi': { state: 'not_home', attributes: { friendly_name: 'Delfi', device_trackers: ['device_tracker.b'] } },
      'person.guest': { state: 'home', attributes: { friendly_name: 'Guest', device_trackers: ['device_tracker.c'] } },
      'person.nobody': { state: 'home', attributes: { friendly_name: 'Nobody', device_trackers: [] } },
    },
  }
  return el
}

test('registers the card', () => {
  const window = load()
  assert.equal(window.AnnikaCards[0][0], 'annika-doorbell-card')
})

test('notifications table has exactly two rows: devices and users', () => {
  const el = card()
  const html = el._notificationsHtml(config, el._texts)
  assert.deepEqual([...html.matchAll(/data-test="(\w+)"/g)].map((m) => m[1]), ['devices', 'users'])
  assert.equal((html.match(/data-notify=/g) || []).length, 4)
  assert.ok(html.includes('At home') && html.includes('Away') && html.includes('Test'))
})

test('presence group lists people and offers only those with a tracker, not already in it', () => {
  const el = card()
  const html = el._notificationsHtml(config, el._texts)
  assert.ok(html.includes('data-person-remove="person.golf"'))
  assert.ok(html.includes('value="person.guest"'))
  assert.ok(!html.includes('value="person.nobody"'))
  assert.ok(!html.includes('value="person.golf"'))
  assert.ok(html.includes('Now: away · 0 of 2 home'))
})

test('talk panel has the two checkboxes only', () => {
  const el = card()
  const html = el._talkHtml(config, el._texts)
  assert.deepEqual([...html.matchAll(/data-talk="(\w+)"/g)].map((m) => m[1]), ['mute_speaker', 'auto_off'])
})

test('tile has speaker, mic and gear, and the gear is left out in settings', () => {
  const el = card()
  const t = el._texts
  const tile = el._tileHtml(config.doorbells[0], t, true)
  assert.ok(tile.includes('data-speaker="front"') && tile.includes('data-mic="front"') && tile.includes('data-settings="front"'))
  assert.ok(!el._tileHtml(config.doorbells[0], t, false).includes('data-settings='))
})

test('speaker is locked while the microphone is on, unless that is turned off', () => {
  const el = card()
  const talk = el._talkState('front')
  talk.speaker = true
  assert.equal(el._speakerAudible('front'), true)
  talk.mic = 'on'
  assert.equal(el._speakerLocked('front'), true)
  assert.equal(el._speakerAudible('front'), false)
  config.talk.mute_speaker = false
  assert.equal(el._speakerAudible('front'), true)
  config.talk.mute_speaker = true
})

test('speaker and microphone start off', () => {
  const el = card()
  const talk = el._talkState('front')
  assert.equal(talk.speaker, false)
  assert.equal(talk.mic, 'off')
  assert.equal(el._speakerAudible('front'), false)
})

test('turning the microphone on without a player says it cannot talk', async () => {
  const el = card()
  el._syncTalk = () => {}
  await el._toggleMic('front')
  const talk = el._talkState('front')
  assert.equal(talk.mic, 'off')
  assert.equal(talk.message, el._texts.cannot_talk)
})

test('turning the microphone on starts it, applies the speaker rule and schedules auto off', async () => {
  const el = card()
  el._syncTalk = () => {}
  const calls = []
  el._players = { front: { failed: false, startMic: async () => calls.push('start'), stopMic: async () => calls.push('stop'), setMuted: (m) => calls.push(`muted:${m}`) } }
  el._talkState('front').speaker = true
  await el._toggleMic('front')
  assert.equal(el._talkState('front').mic, 'on')
  assert.deepEqual(calls, ['start', 'muted:true'])
  assert.ok(el._talkState('front').timer)
  await el._toggleMic('front')
  assert.equal(el._talkState('front').mic, 'off')
  assert.equal(el._talkState('front').timer, null)
  assert.deepEqual(calls.slice(2), ['stop', 'muted:false'])
})

test('microphone errors are explained', () => {
  const el = card()
  const t = el._texts
  assert.equal(el._micError({ name: 'NotAllowedError' }), t.mic_denied)
  assert.equal(el._micError({ name: 'InsecureContext' }), t.mic_insecure)
  assert.equal(el._micError({ name: 'Other' }), t.mic_error)
})

test('settings tiles: select, number, restart button', () => {
  const el = card()
  el._hass.entities = { 'select.a': { device_id: 'd' }, 'number.b': { device_id: 'd' }, 'button.c': { device_id: 'd' } }
  el._hass.states['select.a'] = { attributes: { friendly_name: 'A' } }
  el._hass.states['number.b'] = { attributes: { friendly_name: 'B', mode: 'box' } }
  el._hass.states['button.c'] = { attributes: { friendly_name: 'C', device_class: 'restart' } }
  const tile = (id) => JSON.stringify(el._settingTile(id))
  assert.ok(tile('select.a').includes('select-options'))
  assert.ok(tile('number.b').includes('numeric-input'))
  assert.ok(tile('button.c').includes('confirmation'))
})
