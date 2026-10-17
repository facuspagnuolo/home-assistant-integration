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
