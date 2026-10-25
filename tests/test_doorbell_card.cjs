const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

const www = '../custom_components/annika/resources/www/'

// annika-common.js (the helpers, the player and the talk buttons) and then the card, the way
// Home Assistant loads them. Returns the card's class, defined by common's registration.
function loadCard(extra = {}, tag = 'annika-doorbell-card', file = 'annika-doorbell-card.js') {
  const defined = {}
  const window = {
    loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }),
  }
  const context = {
    window, HTMLElement: class {}, CSS: { escape: (value) => value }, setTimeout, clearTimeout, CustomEvent,
    // Home Assistant is "defined" at once, so the cards are registered while they load.
    customElements: { whenDefined: () => ({ then: (run) => { run(); return { then() {} } } }), get: () => undefined,
      define: (name, cls) => { defined[name] = cls } },
    ...extra,
  }
  for (const name of ['annika-common.js', file]) {
    runInNewContext(readFileSync(require.resolve(www + name), 'utf8'), context)
  }
  return defined[tag]
}

const config = {
  notification: true,
  notifications: { devices: { home: true, away: true }, users: { home: false, away: true } },
  presence: {
    home: 0,
    people: [{ entity: 'person.golf', name: 'Golf', home: false }, { entity: 'person.delfi', name: 'Delfi', home: false }],
  },
  talk: { mute_speaker: true, auto_off: true, auto_off_seconds: 60 },
  recording: { home: false, away: true, before: 5, after: 20, keep_days: 14 },
  doorbells: [{ id: 'front', name: 'Front door', entity: 'camera.front', visitor: 'binary_sensor.v', sensors: { person: 'binary_sensor.p' } }],
}

function card() {
  const Card = loadCard()
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
  assert.equal(typeof loadCard(), 'function')
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
  const talk = el._talk.state('front')
  talk.speaker = true
  assert.equal(el._talk.speakerAudible('front'), true)
  talk.mic = 'on'
  assert.equal(el._talk.speakerLocked('front'), true)
  assert.equal(el._talk.speakerAudible('front'), false)
  config.talk.mute_speaker = false
  assert.equal(el._talk.speakerAudible('front'), true)
  config.talk.mute_speaker = true
})

test('speaker and microphone start off', () => {
  const el = card()
  const talk = el._talk.state('front')
  assert.equal(talk.speaker, false)
  assert.equal(talk.mic, 'off')
  assert.equal(el._talk.speakerAudible('front'), false)
})

test('turning the microphone on without a player says it cannot talk', async () => {
  const el = card()
  el._talk.sync = () => {}
  await el._talk.toggleMic('front')
  const talk = el._talk.state('front')
  assert.equal(talk.mic, 'off')
  assert.equal(talk.message, el._texts.cannot_talk)
})

test('turning the microphone on starts it, applies the speaker rule and schedules auto off', async () => {
  const el = card()
  el._talk.sync = () => {}
  const calls = []
  el._players = { front: { failed: false, startMic: async () => calls.push('start'), stopMic: async () => calls.push('stop'), setMuted: (m) => calls.push(`muted:${m}`) } }
  el._talk.state('front').speaker = true
  await el._talk.toggleMic('front')
  assert.equal(el._talk.state('front').mic, 'on')
  assert.deepEqual(calls, ['start', 'muted:true'])
  assert.ok(el._talk.state('front').timer)
  await el._talk.toggleMic('front')
  assert.equal(el._talk.state('front').mic, 'off')
  assert.equal(el._talk.state('front').timer, null)
  assert.deepEqual(calls.slice(2), ['stop', 'muted:false'])
})

test('microphone errors are explained', () => {
  const el = card()
  const t = el._texts
  assert.equal(el._talk.error({ name: 'NotAllowedError' }), t.mic_denied)
  assert.equal(el._talk.error({ name: 'InsecureContext' }), t.mic_insecure)
  assert.equal(el._talk.error({ name: 'Other' }), t.mic_error)
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

test('recording panel: record at home / away and how many days to keep', () => {
  const el = card()
  const html = el._recordingHtml(config, el._texts)
  assert.ok(html.includes('data-rec-when="home"') && html.includes('data-rec-when="away"'))
  assert.equal((html.match(/data-rec-when="away"[^>]*checked/g) || []).length, 1)
  assert.equal((html.match(/data-rec-when="home"[^>]*checked/g) || []).length, 0)
  assert.ok(html.includes('data-rec-days') && html.includes('value="14"'))
})

test('clips: a carousel of thumbnails, with the picture signed when it is under /media', () => {
  const el = card()
  const t = el._texts
  const clips = [
    { id: 'a1', time: new Date().toISOString(), doorbell: 'Main Doorbell', video: 'a.mp4', image: 'a.jpg', notified: true },
    { id: 'b2', time: new Date().toISOString(), doorbell: 'Main Doorbell', video: 'b.mp4', image: null, notified: false },
  ]
  const html = el._clipsHtml({ clips, image_base: '/media/local/snapshots' }, t)
  assert.deepEqual([...html.matchAll(/data-clip="(\w+)"/g)].map((m) => m[1]), ['a1', 'b2'])
  assert.ok(html.includes('data-signed="/media/local/snapshots/a.jpg"'))
  assert.equal((html.match(/class="bell"/g) || []).length, 1)
  assert.ok(el._clipsHtml({ clips, image_base: '/local/snaps' }, t).includes('src="/local/snaps/a.jpg"'))
  assert.ok(el._clipsHtml({ clips: [] }, t).includes('No clips yet'))
})

test('the player asks for the clip from the media source and says when it cannot', async () => {
  const el = card()
  el._syncPlayer = () => {}
  const clip = { id: 'a1', doorbell: 'Main Doorbell', video: 'a.mp4' }
  const asked = []
  el._hass.callWS = async (message) => { asked.push(message.media_content_id); return { url: '/media/x?token=1' } }
  await el._play(clip, { media_base: 'media-source://media_source/local/clips' })
  assert.deepEqual(asked, ['media-source://media_source/local/clips/a.mp4'])
  assert.equal(el._playing.url, '/media/x?token=1')
  await el._play(clip, {})
  assert.equal(el._playing.error, true)
  assert.ok(el._playerHtml(el._texts).includes('data-delete="a1"'))
})

// --- the connections --------------------------------------------------------------------

function rtc() {
  const connections = []
  class FakePC {
    constructor() {
      connections.push(this)
      this.transceivers = []
      this.listeners = {}
      this.iceGatheringState = 'complete'
      this.connectionState = 'new'
    }
    addTransceiver(kind, options) {
      const transceiver = { kind, direction: options.direction, currentDirection: null, replaced: [],
        sender: { replaceTrack: async (track) => { transceiver.replaced.push(track) } } }
      this.transceivers.push(transceiver)
      return transceiver
    }
    createDataChannel() {}
    addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener) }
    removeEventListener() {}
    async createOffer() { return { sdp: 'offer' } }
    async setLocalDescription(description) { this.localDescription = description }
    async setRemoteDescription() {
      for (const t of this.transceivers) t.currentDirection = t.direction === 'sendrecv' ? 'sendrecv' : 'recvonly'
      this.connectionState = 'connected'
      for (const listener of this.listeners.connectionstatechange || []) listener()
    }
    async addIceCandidate() {}
    close() { this.closed = true }
  }
  const track = { stop() { this.stopped = true } }
  const globals = {
    RTCPeerConnection: FakePC,
    MediaStream: class { addTrack() {} },
    document: { createElement: () => ({ setAttribute() {}, play: () => Promise.resolve(), muted: false }) },
    navigator: { mediaDevices: { getUserMedia: async () => ({ getAudioTracks: () => [track] }) } },
    isSecureContext: true,
  }
  const hass = {
    callWS: async () => ({}),
    connection: {
      subscribeMessage: async (callback) => {
        setTimeout(() => callback({ type: 'answer', answer: 'answer' }), 0)
        return () => {}
      },
    },
  }
  return { connections, globals, hass, track }
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 5))

test('the picture connects with no sound; the sound only opens when it is asked for', async () => {
  const { connections, globals, hass, track } = rtc()
  const Player = loadCard(globals).Player
  const player = new Player(hass, 'camera.front')
  await player.connect()
  await settle()
  assert.equal(connections.length, 1)
  assert.deepEqual(connections[0].transceivers.map((t) => t.kind), ['video'])
  assert.equal(player.audioState, 'off')

  await player.ensureAudio()
  await player.ensureAudio()
  assert.equal(connections.length, 2)
  assert.deepEqual(connections[1].transceivers.map((t) => [t.kind, t.direction]), [['audio', 'sendrecv']])
  assert.equal(player.audioState, 'on')
  assert.equal(player.talkSupported, true)

  // Nothing is captured until the microphone is turned on, and stopping it releases it.
  assert.equal(connections[1].transceivers[0].replaced.length, 0)
  await player.startMic()
  assert.equal(player.micOn, true)
  assert.equal(connections[1].transceivers[0].replaced[0], track)
  await player.stopMic()
  assert.equal(track.stopped, true)
  assert.equal(connections[1].transceivers[0].replaced[1], null)

  // Closing the sound leaves the picture running.
  player.closeAudio()
  assert.equal(connections[1].closed, true)
  assert.equal(connections[0].closed, undefined)
  assert.equal(player.audioState, 'off')
  await player.ensureAudio()
  assert.equal(connections.length, 3)
  player.close()
  assert.ok(connections.every((c) => c.closed))
})

test('turning the speaker on opens the sound, then plays it; if it cannot, the speaker goes back off', async () => {
  const el = card()
  el._talk.sync = () => {}
  const events = []
  let fail = false
  el._players = { front: { audioState: 'off', failed: false,
    setAudioWanted: (wanted) => events.push(`wanted:${wanted}`),
    setMuted: (muted) => events.push(`muted:${muted}`),
    ensureAudio: () => (fail ? Promise.reject(new Error('x')) : Promise.resolve()) } }
  el._talk.toggleSpeaker('front')
  assert.equal(el._talk.state('front').audioBusy, true)
  await settle()
  assert.equal(el._talk.state('front').audioBusy, false)
  assert.equal(el._talk.state('front').speaker, true)
  assert.ok(events.includes('muted:false') && events.includes('wanted:true'))

  el._talk.toggleSpeaker('front')
  assert.equal(el._talk.state('front').speaker, false)
  assert.equal(events.at(-1), 'muted:true')

  fail = true
  el._talk.toggleSpeaker('front')
  await settle()
  assert.equal(el._talk.state('front').speaker, false)
  assert.equal(el._talk.state('front').message, el._texts.audio_error)
})

test('features choose what the strip under the doorbell shows and in which order', () => {
  const el = card()
  const t = el._texts
  const doorbell = (features) => ({ ...config.doorbells[0], features })
  const all = el._tileHtml(doorbell(undefined), t, true)
  const at = (html, marker) => html.indexOf(marker)
  assert.ok(at(all, 'data-sensor-state=') < at(all, 'data-speaker=') && at(all, 'data-speaker=') < at(all, 'data-mic=') && at(all, 'data-mic=') < at(all, 'data-settings='))
  assert.equal((all.match(/class="sep"/g) || []).length, 1)

  const some = el._tileHtml(doorbell(['settings', 'mic']), t, true)
  assert.ok(at(some, 'data-settings=') < at(some, 'data-mic='))
  assert.ok(!some.includes('data-speaker=') && !some.includes('data-sensor-state='))
  assert.ok(some.includes('data-talk-message="front"'))

  const quiet = el._tileHtml(doorbell(['sensors', 'settings']), t, true)
  assert.ok(!quiet.includes('data-talk-message=') && !quiet.includes('data-speaker=') && !quiet.includes('class="sep"'))
  assert.ok(!/data-(speaker|mic|settings|sensor-state)=/.test(el._tileHtml(doorbell([]), t, true)))
})

test('hd: a button when the doorbell has a clear stream, and the live stream switches to it', () => {
  const el = card()
  el._hass.states['camera.front'] = {}
  el._hass.states['camera.front_clear'] = {}
  const fluent = { ...config.doorbells[0], entity: 'camera.front_fluent', features: ['hd', 'settings'] }
  el._hass.states['camera.front_fluent'] = {}
  const t = el._texts
  assert.ok(el._tileHtml(fluent, t, true).includes('data-hd="front"'))
  assert.equal(el._liveEntityFor(fluent), 'camera.front_fluent')
  el._hd.add('front')
  assert.equal(el._liveEntityFor(fluent), 'camera.front_clear')
  // No clear stream (or already the clear one): no button.
  assert.ok(!el._tileHtml({ ...fluent, entity: 'camera.front_clear' }, t, true).includes('data-hd='))
  delete el._hass.states['camera.front_clear']
  assert.ok(!el._tileHtml(fluent, t, true).includes('data-hd='))
})

test('tapping a picture played by the Player opens the camera dialog; a picture card handles its own tap', () => {
  const el = card()
  const opened = []
  el.dispatchEvent = (event) => opened.push([event.type, event.detail.entityId, event.bubbles, event.composed])
  el._players = { front: { entity: 'camera.front_fluent' } }
  el._moreInfo('front')
  el._moreInfo('back')
  assert.deepEqual(opened, [['hass-more-info', 'camera.front_fluent', true, true]])
})
