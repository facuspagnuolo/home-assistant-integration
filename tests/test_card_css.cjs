// The card styles are written one rule per line and scoped by a small helper: a rule that is
// left open (an unclosed @media, say) silently drops every rule that follows it.
const test = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')

const WWW = path.join(__dirname, '..', 'custom_components', 'annika', 'resources', 'www')

for (const file of ['annika-heating-card.js', 'annika-ac-card.js']) {
  test(`${file}: the stylesheet is balanced and every line is a complete rule`, () => {
    const source = fs.readFileSync(path.join(WWW, file), 'utf8')
    const start = source.indexOf('scope(`') + 'scope(`'.length
    const css = source.slice(start, source.indexOf('`)', start))
    let depth = 0
    css.split('\n').forEach((line, index) => {
      const opens = (line.match(/\{/g) || []).length
      const closes = (line.match(/\}/g) || []).length
      depth += opens - closes
      assert.strictEqual(depth, 0, `${file}: css line ${index + 1} leaves a rule open: ${line.slice(0, 80)}`)
    })
  })
}
