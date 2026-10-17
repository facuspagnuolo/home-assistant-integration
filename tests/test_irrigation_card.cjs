const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { test } = require('node:test')
const { runInNewContext } = require('node:vm')

test('zone tiles use manual switches, keep zone names and history, and support older sensors', async () => {
  class Element {
    constructor() {
      this.classList = { add() {} }
      this.style = { setProperty() {} }
    }
    appendChild() {}
    insertBefore() {}
    addEventListener() {}
    querySelector() { return new Element() }
  }
  const configs = []
  const window = {
    Annika: {
      tileConfig: (item, options) => ({ type: 'tile', ...options, ...item }),
      headingConfig: (heading) => ({ type: 'heading', heading }),
      gridConfig: (cards, columns) => ({ type: 'grid', cards, columns }),
    },
    loadCardHelpers: async () => ({ createCardElement(config) {
      configs.push(config)
      return new Element()
    } }),
  }
  runInNewContext(readFileSync(require.resolve('../custom_components/annika/resources/www/annika-irrigation-card.js'), 'utf8'), {
    window, HTMLElement: Element, document: { createElement: () => new Element() },
  })
  const Card = window.AnnikaCards[0][1]
  const card = new Card()
  card._config = {}
  card._labels = {}
  card._headings = {}
  card._table = () => new Element()
  card._hass = { states: {
    'switch.front': { attributes: { friendly_name: 'Frente' } },
    'switch.back': { attributes: { friendly_name: 'Fondo' } },
  } }
  await card._build({ entities: { manual_minutes: 'number.limit' }, zones: [
    { entity: 'switch.front', manual: 'switch.manual_front' },
    { entity: 'switch.back', name: 'Patio' },
  ] })
  const zoneGrid = configs.find((config) => config.type === 'grid' && config.cards.some((tile) => tile.entity === 'switch.manual_front'))
  assert.equal(zoneGrid.cards[0].entity, 'switch.manual_front')
  assert.equal(zoneGrid.cards[0].name, 'Frente')
  assert.equal(zoneGrid.cards[1].entity, 'switch.back')
  assert.equal(zoneGrid.cards[1].name, 'Patio')
  const history = configs.flatMap((config) => config.cards || []).find((config) => config.type === 'history-graph')
  assert.equal(history.entities[0].entity, 'switch.front')
  assert.equal(history.entities[1].entity, 'switch.back')
})
