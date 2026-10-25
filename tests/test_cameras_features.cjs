const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

const www = '../custom_components/annika/resources/www/'

// annika-common.js and then the cameras card, the way Home Assistant loads them.
function load() {
  const defined = {}
  const window = { loadCardHelpers: async () => ({ createCardElement: async (config) => ({ config }) }) }
  const context = {
    window, HTMLElement: class {}, CSS: { escape: (value) => value }, setTimeout, clearTimeout, CustomEvent,
    customElements: { whenDefined: () => ({ then: (run) => { run(); return { then() {} } } }), get: () => undefined,
      define: (name, cls) => { defined[name] = cls } },
  }
  for (const name of ['annika-common.js', 'annika-cameras-card.js']) {
    runInNewContext(readFileSync(require.resolve(www + name), 'utf8'), context)
  }
  return { window, Card: defined['annika-cameras-card'] }
}

const camera = (extra = {}) => ({ id: 'front', name: 'Front', entity: 'camera.front_clear', sensors: { person: 'binary_sensor.p' }, ...extra })

function card(cameras = [camera()]) {
  const { window, Card } = load()
  const el = new Card()
  el._render = () => {}
  el.setConfig({ entity: 'sensor.annika_cameras' })
  el._hass = {
    language: 'en',
    states: {
      'sensor.annika_cameras': { attributes: { config: { cameras, talk: {} } } },
      'camera.front_clear': {}, 'camera.front_fluent': {},
      'binary_sensor.p': { state: 'off' },
    },
  }
  return { el, window }
}

const order = (html, markers) => markers.map((marker) => html.indexOf(marker))

test('the strip starts as hd, sensors and settings', () => {
  const { el } = card()
  const html = el._camerasHtml({ cameras: [camera()] }, el._texts)
  const at = order(html, ['data-hd=', 'data-sensor-state=', 'data-settings='])
  assert.ok(at.every((n) => n >= 0) && at[0] < at[1] && at[1] < at[2])
  assert.ok(!html.includes('data-speaker=') && !html.includes('data-mic=') && !html.includes('data-talk-message='))
})

test('features choose what the strip shows and in which order', () => {
  const { el } = card()
  const t = el._texts
  const html = el._camerasHtml({ cameras: [camera({ features: ['mic', 'sensors', 'audio'] })] }, t)
  const at = order(html, ['data-mic=', 'data-sensor-state=', 'data-speaker='])
  assert.ok(at.every((n) => n >= 0) && at[0] < at[1] && at[1] < at[2])
  assert.ok(!html.includes('data-hd=') && !html.includes('data-settings='))
  assert.ok(html.includes('data-talk-message="front"'))
  const bare = el._camerasHtml({ cameras: [camera({ features: [] })] }, t)
  assert.ok(!/data-(hd|settings|speaker|mic|sensor-state)=/.test(bare))
})

test('hd only shows for a camera that has both streams', () => {
  const { el } = card()
  el._hass.states = { 'sensor.annika_cameras': el._hass.states['sensor.annika_cameras'], 'camera.lone': {} }
  const html = el._camerasHtml({ cameras: [camera({ entity: 'camera.lone', features: ['hd', 'settings'] })] }, el._texts)
  assert.ok(!html.includes('data-hd=') && html.includes('data-settings='))
})

test('a camera with audio or mic plays through our own player, kept between renders and changed with HD', () => {
  const { el, window } = card()
  const players = []
  window.Annika.Player = class {
    constructor(hass, entity) { this.entity = entity; this.video = { play() {} }; players.push(this) }
    connect() {}
    close() { this.closed = true }
    setMuted() {}
  }
  const front = camera({ features: ['audio', 'mic'] })
  assert.equal(el._hasAudio(front), true)
  assert.equal(el._hasAudio(camera()), false)
  const holder = { replaceChildren(child) { this.child = child } }
  el._talk.sync = () => {}
  el._mountPlayer(front, holder)
  el._mountPlayer(front, holder)
  assert.equal(players.length, 1)
  assert.equal(players[0].entity, 'camera.front_fluent')
  assert.equal(holder.child, players[0].video)

  el._talk.state('front').speaker = true
  el._hd.add('front')
  el._mountPlayer(front, holder)
  assert.equal(players[0].closed, true)
  assert.equal(players.length, 2)
  assert.equal(players[1].entity, 'camera.front_clear')
  assert.equal(el._talk.state('front').speaker, false)
})

test('a camera with no audio feature still uses the picture card', async () => {
  const { el } = card()
  const mounted = []
  el._mountPlayer = (c) => mounted.push(c.id)
  el.querySelector = () => ({ replaceChildren() {} })
  await el._mountLive({ cameras: [camera()] })
  assert.deepEqual(mounted, [])
})

test('tapping a picture played by the Player opens the camera dialog; a picture card handles its own tap', () => {
  const { el } = card()
  const opened = []
  el.dispatchEvent = (event) => opened.push([event.type, event.detail.entityId, event.bubbles, event.composed])
  el._players = { front: { entity: 'camera.front_fluent' } }
  el._moreInfo('front')
  el._moreInfo('back')
  assert.deepEqual(opened, [['hass-more-info', 'camera.front_fluent', true, true]])
})
