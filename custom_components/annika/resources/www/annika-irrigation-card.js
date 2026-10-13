// Annika irrigation card.
//
// The dashboard for the irrigation schedule the Annika integration runs (see
// irrigation.py). Everything it shows comes from the integration's status
// sensor, `sensor.irrigation`, whose attributes map the seasons, groups,
// zones and every setting entity — so the card needs no entity list: change
// the seasons or zones in the integration's YAML, restart, and the card
// follows.
//
//   Top row, three columns:
//     1. Schedule: on/off, run now, stop, and what comes next
//     2. Start: at sunrise (with an offset) or at a fixed time
//     3. Rain: the rain sensor, the controller's rain delay, and how many
//        days of delay the integration sets when it rains (only when the
//        integration was given both a rain sensor and a rain delay)
//   Then, full width:
//     Days and minutes: one row per season, a checkbox per weekday and the
//       minutes each group of zones runs. Today's season is marked.
//     Zones: a tile each.
//     History: the zones over the last hours.
//
// Usage in a dashboard view:
//   type: custom:annika-irrigation-card
//   entity: sensor.irrigation   # optional, the integration's status sensor
//   history_hours: 48           # optional (default 48)
//   zone_columns: 2             # optional, zone tiles per row (default 2)
//   zone_icon: mdi:sprinkler    # optional (default mdi:sprinkler-variant)
//   color: primary              # optional, tile color (default primary)
//   language: es                # optional; by default the user's Home Assistant
//                               # language (English and Spanish are built in)
//   headings:                   # optional, override single headings
//     schedule: Riego
//     start: Inicio
//     rain: Lluvia
//     days: Días y minutos
//     zones: Zonas
//     history: Historial
//   labels:                     # optional, override single texts
//     next: Próximo riego
//     none: Sin riegos programados
//     disabled: Programa apagado
//     running: Regando
//     season: Temporada
//     now: hoy
//     automation: Lo maneja     # with `automation:` set in the integration
//     on: prendida
//     off: apagada
//   grid_options:
//     columns: full
;(() => {
  const CARD = 'annika-irrigation-card'
  const DEFAULT_ENTITY = 'sensor.irrigation'
  const DEFAULT_HISTORY_HOURS = 48
  const DEFAULT_ZONE_COLUMNS = 2
  const NARROW_WIDTH = 640
  const NARROW_ZONE_COLUMNS = 2
  const DEFAULT_COLOR = 'primary'
  const DEFAULT_ZONE_ICON = 'mdi:sprinkler-variant'
  const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
  // 1 January 2024 was a Monday: Intl names the weekdays from it.
  const A_MONDAY = Date.UTC(2024, 0, 1, 12)

  // The card's own texts, by Home Assistant language (see Annika.textsFor in
  // annika-common.js). `headings:` and `labels:` in the card config override
  // single texts on top.
  const TEXTS = {
    en: {
      headings: {
        schedule: 'Irrigation',
        start: 'Start',
        rain: 'Rain',
        days: 'Days and minutes',
        zones: 'Zones',
        history: 'History',
      },
      labels: {
        next: 'Next run',
        none: 'Nothing scheduled',
        disabled: 'Schedule off',
        running: 'Watering',
        season: 'Season',
        now: 'today',
        minutes: 'min',
        automation: 'Run by',
        on: 'on',
        off: 'off',
        missing: 'The Annika irrigation sensor was not found. Is `irrigation` set in the Annika configuration?',
      },
    },
    es: {
      headings: {
        schedule: 'Riego',
        start: 'Inicio',
        rain: 'Lluvia',
        days: 'Días y minutos',
        zones: 'Zonas',
        history: 'Historial',
      },
      labels: {
        next: 'Próximo riego',
        none: 'Sin riegos programados',
        disabled: 'Programa apagado',
        running: 'Regando',
        season: 'Temporada',
        now: 'hoy',
        minutes: 'min',
        automation: 'Lo maneja',
        on: 'prendida',
        off: 'apagada',
        missing: 'No se encontró el sensor de riego de Annika. ¿Está `irrigation` en la configuración de Annika?',
      },
    },
  }

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  }

  // What the card is built from. When it changes (seasons or zones edited in
  // YAML, then a restart) the card is built again; anything else is a value
  // that changes in place.
  function structureOf(attributes) {
    const { groups, seasons, zones, entities } = attributes
    return JSON.stringify({ groups, seasons, zones, entities })
  }

  function pressAction(entity) {
    return { action: 'perform-action', perform_action: 'button.press', target: { entity_id: entity } }
  }

  class AnnikaIrrigationCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {}
      this._entity = this._config.entity || DEFAULT_ENTITY
      this._texts = undefined
      this._resolveTexts()
      this._structure = this._hass ? this._structureNow() : undefined
      this._cards = undefined
      this._render()
    }

    // The zone tiles live inside a stock card's shadow root, out of reach of
    // this card's CSS, so their columns follow the width here: two on a phone.
    connectedCallback() {
      this.style.display = 'block'
      if (this._observer || typeof ResizeObserver === 'undefined') return
      this._observer = new ResizeObserver(() => {
        const narrow = this.clientWidth > 0 && this.clientWidth <= NARROW_WIDTH
        if (narrow === this._narrow) return
        this._narrow = narrow
        if (this._hass) this.hass = this._hass
      })
      this._observer.observe(this)
    }

    disconnectedCallback() {
      if (this._observer) this._observer.disconnect()
      this._observer = undefined
    }

    set hass(hass) {
      this._hass = hass
      this._resolveTexts()
      const structure = this._structureNow()
      if (structure !== this._structure) {
        this._structure = structure
        this._cards = undefined
        this._render()
        return
      }
      if (this._cards) for (const card of this._cards) card.hass = hass
      this._update()
    }

    // The texts follow the card's `language`, or else the user's Home
    // Assistant language. A change of language builds the card again, since
    // the headings are part of what it is built from.
    _resolveTexts() {
      const lang = annika().language(this._hass, this._config)
      if (this._texts && this._texts.lang === lang) return
      const { headings, labels } = annika().textsFor(TEXTS, lang)
      this._texts = { lang }
      this._headings = { ...headings, ...((this._config && this._config.headings) || {}) }
      this._labels = { ...labels, ...((this._config && this._config.labels) || {}) }
    }

    _structureNow() {
      const state = this._hass.states[this._entity]
      return (state ? structureOf(state.attributes) : 'missing') + `|${this._texts.lang}|${this._narrow ? 'narrow' : 'wide'}`
    }

    getCardSize() {
      const state = this._hass && this._hass.states[this._entity]
      const seasons = state ? (state.attributes.seasons || []).length : 3
      const zones = state ? (state.attributes.zones || []).length : 4
      return 8 + seasons + Math.ceil(zones / 2)
    }

    getGridOptions() {
      return { columns: 'full' }
    }

    getLayoutOptions() {
      return { grid_columns: 'full' }
    }

    async _render() {
      if (!this._hass || !this._config || this._cards || this._building) return
      const state = this._hass.states[this._entity]
      if (!state) {
        this.innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(this._labels.missing)}</div></ha-card>`
        return
      }

      this._building = true
      const built = this._structureNow()
      try {
        await this._build(state.attributes)
      } finally {
        this._building = false
      }
      // The seasons or zones changed while it was building: build again.
      if (this._structureNow() !== built) {
        this._cards = undefined
        return this._render()
      }
      this._update()
    }

    async _build(attributes) {
      const { tileConfig, headingConfig, gridConfig, HEADING_CSS, CHECKBOX_CSS, HISTORY_CSS } = annika()
      const helpers = await window.loadCardHelpers()
      const entities = attributes.entities || {}
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color
      const headings = this._headings
      const tile = (entity, options = {}) => tileConfig({ entity, color }, options)

      const scheduleCards = [
        headingConfig(headings.schedule),
        // With an automation of the house's own, the toggle is that automation.
        tile(entities.automation || entities.enabled, { features: [{ type: 'toggle' }] }),
        gridConfig(
          [
            // A button's state is when it was last pressed: nothing worth a line.
            tile(entities.run, { hide_state: true, tap_action: pressAction(entities.run), icon_tap_action: pressAction(entities.run) }),
            tile(entities.stop, { hide_state: true, tap_action: pressAction(entities.stop), icon_tap_action: pressAction(entities.stop) }),
          ],
          2,
        ),
      ]

      // Only the control for the chosen mode shows; _update() swaps them. Not
      // a `conditional` card: built outside a view it never re-checks.
      const startCards = [
        headingConfig(headings.start),
        tile(entities.start_mode, { features: [{ type: 'select-options' }] }),
      ]
      const offsetConfig = tile(entities.sunrise_offset, { features: [{ type: 'numeric-input', style: 'buttons' }] })
      const timeConfig = tile(entities.start_time)

      const rainCards = [headingConfig(headings.rain)]
      if (entities.rain_sensor) rainCards.push(tile(entities.rain_sensor))
      if (entities.rain_delay) {
        rainCards.push(tile(entities.rain_delay, { features: [{ type: 'numeric-input', style: 'buttons' }] }))
      }
      if (entities.rain_delay_after_rain) {
        rainCards.push(tile(entities.rain_delay_after_rain, { features: [{ type: 'numeric-input', style: 'buttons' }] }))
      }

      const zones = attributes.zones || []
      const zoneNames = new Map(zones.map((zone) => [zone.entity, zone.name]))
      const zonesConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig(headings.zones),
          gridConfig(
            zones.map((zone) =>
              tileConfig({ entity: zone.entity, name: zone.name || undefined, icon: this._config.zone_icon || DEFAULT_ZONE_ICON, color }),
            ),
            this._narrow ? Math.min(NARROW_ZONE_COLUMNS, Number(this._config.zone_columns) || DEFAULT_ZONE_COLUMNS) : Number(this._config.zone_columns) || DEFAULT_ZONE_COLUMNS,
          ),
        ],
      }
      const historyConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig(headings.history),
          {
            type: 'history-graph',
            refresh_interval: 60,
            hours_to_show: Number(this._config.history_hours) || DEFAULT_HISTORY_HOURS,
            entities: zones.map((zone) => ({ entity: zone.entity, name: zoneNames.get(zone.entity) || undefined })),
          },
        ],
      }

      const cards = []
      const build = (config) => {
        const element = helpers.createCardElement(config)
        element.hass = this._hass
        cards.push(element)
        return element
      }

      const column = (configs, extra) => {
        const element = document.createElement('div')
        element.className = 'annika-irr-column'
        for (const config of configs) element.appendChild(build(config))
        if (extra) element.appendChild(extra)
        return element
      }

      this._status = document.createElement('div')
      this._status.className = 'annika-irr-status'

      this.innerHTML = `
        <style>
          ${HEADING_CSS}
          ${CHECKBOX_CSS}
          ${HISTORY_CSS}
          .annika-irr-top { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; align-items: start; }
          .annika-irr-top > * { min-width: 0; }
          .annika-irr-column { display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
          .annika-irr-block { margin-top: 16px; display: block; height: auto; }
          .annika-irr-status { color: var(--secondary-text-color); font-size: 14px; line-height: 1.4; padding: 4px 4px 0; }
          .annika-irr-status strong { color: var(--primary-text-color); font-weight: 500; }
          .annika-irr-table-card { padding: 8px 0; }
          .annika-irr-scroll { overflow-x: auto; }
          .annika-irr-table { border-collapse: collapse; width: 100%; font-size: 14px; }
          .annika-irr-table th, .annika-irr-table td { padding: 8px 6px; text-align: center; white-space: nowrap; }
          .annika-irr-table th { color: var(--secondary-text-color); font-weight: 500; font-size: 12px; text-transform: capitalize; }
          .annika-irr-table th.season, .annika-irr-table td.season { text-align: left; padding-left: 16px; }
          .annika-irr-table tbody tr { border-top: 1px solid var(--divider-color); }
          .annika-irr-table tr.current td.season { box-shadow: inset 3px 0 0 var(--primary-color); }
          .annika-irr-table .name { color: var(--primary-text-color); font-weight: 500; }
          .annika-irr-table .months { color: var(--secondary-text-color); font-size: 12px; }
          .annika-irr-table .now { color: var(--primary-color); font-size: 12px; margin-left: 6px; }
          .annika-irr-table input[type=number] {
            width: 56px; padding: 4px 6px; font: inherit; text-align: right;
            color: var(--primary-text-color); background: var(--secondary-background-color, transparent);
            border: 1px solid var(--divider-color); border-radius: 6px;
          }
          .annika-irr-table .unit { color: var(--secondary-text-color); font-size: 12px; margin-left: 4px; }
          .annika-irr-table .gap { border-left: 1px solid var(--divider-color); }
          annika-irrigation-card { display: block; container-type: inline-size; }
          @media (max-width: 800px) { .annika-irr-top { grid-template-columns: 1fr; } }
          /* A narrow card (a phone): zones two by two, and each season is a
             block: name, then the days, then the minutes of each group. */
          @container (max-width: 640px) /* NARROW_WIDTH */ {
            .annika-irr-scroll { overflow-x: visible; }
            .annika-irr-table, .annika-irr-table tbody { display: block; width: 100%; }
            .annika-irr-table thead { display: none; }
            .annika-irr-table tr { display: grid; grid-template-columns: repeat(14, 1fr); align-items: center; padding: 6px 8px; }
            .annika-irr-table td { padding: 4px 0; }
            .annika-irr-table td.season { grid-column: 1 / -1; padding: 4px 8px; text-align: left; }
            .annika-irr-table td.day { grid-column: span 2; }
            .annika-irr-table td.day::before { content: attr(data-label); display: block; color: var(--secondary-text-color); font-size: 11px; text-transform: capitalize; margin-bottom: 4px; }
            .annika-irr-table td.group { grid-column: span 7; text-align: left; padding: 8px 8px 0; border-left: 0; }
            .annika-irr-table td.group::before { content: attr(data-label); display: block; color: var(--secondary-text-color); font-size: 11px; margin-bottom: 4px; }
          }
        </style>
      `
      const top = document.createElement('div')
      top.className = 'annika-irr-top'
      top.appendChild(column(scheduleCards, this._status))
      const startColumn = column(startCards)
      this._offsetElement = build(offsetConfig)
      this._timeElement = build(timeConfig)
      startColumn.appendChild(this._offsetElement)
      startColumn.appendChild(this._timeElement)
      this._startModeEntity = entities.start_mode
      top.appendChild(startColumn)
      top.appendChild(column(rainCards))
      this.appendChild(top)

      const days = document.createElement('div')
      days.className = 'annika-irr-block annika-irr-column'
      days.appendChild(build(headingConfig(headings.days)))
      days.appendChild(this._table(attributes))
      this.appendChild(days)

      const zonesElement = build(zonesConfig)
      zonesElement.classList.add('annika-irr-block')
      this.appendChild(zonesElement)
      if (zones.length > 0) {
        const history = build(historyConfig)
        history.classList.add('annika-irr-block', 'annika-history')
        this.appendChild(history)
      }

      this._cards = cards
    }

    // The one part with no stock card: a season x weekday grid of checkboxes
    // and the minutes per group, each bound to its own entity.
    _table(attributes) {
      const hass = this._hass
      const lang = annika().language(hass, this._config)
      const weekday = new Intl.DateTimeFormat(lang, { weekday: 'short', timeZone: 'UTC' })
      const month = new Intl.DateTimeFormat(lang, { month: 'short', timeZone: 'UTC' })
      const dayNames = WEEKDAYS.map((_, index) => weekday.format(new Date(A_MONDAY + index * 86400000)))
      const groups = attributes.groups || []
      const seasons = attributes.seasons || []

      const head = `
        <tr>
          <th class="season">${escapeHtml(this._labels.season)}</th>
          ${dayNames.map((name) => `<th>${escapeHtml(name)}</th>`).join('')}
          ${groups.map((group, index) => `<th class="${index === 0 ? 'gap' : ''}">${escapeHtml(group.name)}</th>`).join('')}
        </tr>`

      const rows = seasons
        .map((season) => {
          const months = (season.months || []).map((m) => month.format(new Date(Date.UTC(2024, m - 1, 1)))).join(', ')
          const checks = WEEKDAYS.map((day, index) => {
            const entity = season.days && season.days[day]
            return `<td class="day" data-label="${escapeHtml(dayNames[index])}"><input type="checkbox" class="annika-check" data-entity="${escapeHtml(entity || '')}" aria-label="${escapeHtml(`${season.name} ${dayNames[index]}`)}" ${entity ? '' : 'disabled'}></td>`
          }).join('')
          const minutes = groups
            .map((group, index) => {
              const entity = season.minutes && season.minutes[group.key]
              return `<td class="${index === 0 ? 'gap ' : ''}group" data-label="${escapeHtml(group.name)}"><input type="number" min="0" max="120" step="1" inputmode="numeric" data-entity="${escapeHtml(entity || '')}" aria-label="${escapeHtml(`${season.name} ${group.name}`)}" ${entity ? '' : 'disabled'}><span class="unit">${escapeHtml(this._labels.minutes)}</span></td>`
            })
            .join('')
          return `
            <tr data-season="${escapeHtml(season.key)}">
              <td class="season"><span class="name">${escapeHtml(season.name)}</span><span class="now" hidden>${escapeHtml(this._labels.now)}</span><div class="months">${escapeHtml(months)}</div></td>
              ${checks}
              ${minutes}
            </tr>`
        })
        .join('')

      const card = document.createElement('ha-card')
      card.className = 'annika-irr-table-card'
      card.innerHTML = `<div class="annika-irr-scroll"><table class="annika-irr-table"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`

      card.addEventListener('change', (event) => {
        const input = event.target
        const entity = input && input.dataset && input.dataset.entity
        if (!entity || !this._hass) return
        if (input.type === 'checkbox') {
          this._hass.callService('switch', input.checked ? 'turn_on' : 'turn_off', { entity_id: entity })
          return
        }
        const value = Number(input.value)
        if (input.value === '' || !Number.isInteger(value) || value < Number(input.min) || value > Number(input.max)) {
          this._updateInput(input, true)
          return
        }
        this._hass.callService('number', 'set_value', { entity_id: entity, value })
      })
      card.addEventListener('focusout', (event) => {
        if (event.target && event.target.type === 'number') this._updateInput(event.target, true)
      })

      this._tableCard = card
      return card
    }

    _updateInput(input, force) {
      const state = this._hass && this._hass.states[input.dataset.entity]
      if (input.type === 'checkbox') {
        input.checked = !!state && state.state === 'on'
        input.disabled = !state || state.state === 'unavailable'
        return
      }
      // Never under someone's fingers: a value typed and not yet sent stays.
      if (!force && document.activeElement === input) return
      if (!state || Number.isNaN(Number(state.state))) {
        input.value = ''
        return
      }
      input.value = String(Math.round(Number(state.state)))
    }

    _update() {
      if (!this._hass || !this._tableCard) return
      const state = this._hass.states[this._entity]
      if (!state) return
      const attributes = state.attributes

      for (const input of this._tableCard.querySelectorAll('input[data-entity]')) {
        if (input.dataset.entity) this._updateInput(input, false)
      }
      for (const row of this._tableCard.querySelectorAll('tr[data-season]')) {
        const current = row.dataset.season === attributes.current_season
        row.classList.toggle('current', current)
        row.querySelector('.now').hidden = !current
      }

      if (this._status) this._status.innerHTML = this._statusLine(state)

      const mode = this._hass.states[this._startModeEntity]
      const fixedTime = !!mode && mode.state === 'time'
      if (this._offsetElement) this._offsetElement.style.display = fixedTime ? 'none' : ''
      if (this._timeElement) this._timeElement.style.display = fixedTime ? '' : 'none'
    }

    _statusLine(state) {
      const labels = this._labels
      const attributes = state.attributes
      if (state.state === 'running') {
        const zone = (attributes.zones || []).find((item) => item.entity === attributes.current_zone)
        const name = zone && (zone.name || this._friendlyName(zone.entity))
        return `<strong>${escapeHtml(labels.running)}</strong>${name ? ` · ${escapeHtml(name)}` : ''}`
      }
      if (state.state === 'disabled') return `<strong>${escapeHtml(labels.disabled)}</strong>`
      if (attributes.automation) {
        const automation = this._hass.states[attributes.automation]
        const name = this._friendlyName(attributes.automation)
        const on = !!automation && automation.state === 'on'
        return `${escapeHtml(labels.automation)}: <strong>${escapeHtml(name)}</strong> · ${escapeHtml(on ? labels.on : labels.off)}`
      }
      if (!attributes.next_run) return escapeHtml(labels.none)
      return `${escapeHtml(labels.next)}: <strong>${escapeHtml(this._when(attributes.next_run))}</strong>`
    }

    _friendlyName(entity) {
      const state = this._hass.states[entity]
      return (state && state.attributes.friendly_name) || entity
    }

    _when(iso) {
      const hass = this._hass
      const timeZone = (hass.config && hass.config.time_zone) || undefined
      return new Intl.DateTimeFormat(annika().language(hass, this._config), {
        timeZone,
        weekday: 'long',
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(iso))
    }
  }

  // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaIrrigationCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Irrigation',
    description: 'The Annika irrigation schedule: days per season, minutes per group, start time, rain and zones.',
  })
})()
