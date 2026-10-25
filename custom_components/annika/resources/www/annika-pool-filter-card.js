// Annika schedule card.
//
// The dashboard for a seasonal timetable the Annika integration runs (see
// pool_filter.py): one switch — the pool filter — that comes on at a few times
// of day for a number of minutes, with the times and the minutes changing
// with the season. Everything it shows comes from the integration's status
// sensor, whose attributes map the seasons, their runs and every setting
// entity, so the card needs no entity list: change the seasons in the
// integration's YAML, restart, and the card follows.
//
//   Top row, small tiles: the timetable's on/off, the switch itself (to turn
//   it on or off by hand), run now, stop and, with `notify_view`, whether
//   runs send a notification; four in a row, two by two on a
//   phone; under them, what comes next
//   Then, full width:
//     Timetable: one row per season, a checkbox and a time for each run, and
//       the minutes each run lasts. Today's season is marked.
//     History: the switch over the last hours.
//
// Usage in a dashboard view:
//   type: custom:annika-pool-filter-card
//   entity: sensor.pool_filter  # the status sensor
//   history_hours: 48           # optional (default 48)
//   color: primary              # optional, tile color (default primary)
//   language: es                # optional; by default the Home Assistant
//                               # language (English and Spanish are built in)
//   headings:                   # optional, override single headings
//     schedule: Programa
//     timetable: Horarios
//     history: Historial
//   labels:                     # optional, override single texts
//     next: Próxima corrida
//     none: Sin corridas programadas
//     disabled: Programa apagado
//     running: Prendida
//     until: hasta
//     season: Temporada
//     runs: Horarios
//     now: hoy
//     automation: Lo maneja
//     on: prendida
//     off: apagada
//   grid_options:
//     columns: full
;(() => {
  const CARD = 'annika-pool-filter-card'
  const DEFAULT_HISTORY_HOURS = 48
  const DEFAULT_COLOR = 'primary'
  const NARROW_WIDTH = 640
  const TILE_COLUMNS = 4
  const NARROW_TILE_COLUMNS = 2

  // The card's own texts, by Home Assistant language (see Annika.textsFor in
  // annika-common.js). `headings:` and `labels:` in the card config override
  // single texts on top.
  const TEXTS = {
    en: {
      headings: { schedule: 'Schedule', timetable: 'Timetable', history: 'History' },
      labels: {
        next: 'Next run',
        none: 'Nothing scheduled',
        disabled: 'Schedule off',
        running: 'On',
        until: 'until',
        season: 'Season',
        runs: 'Runs',
        now: 'today',
        minutes: 'min',
        tile_schedule: 'Schedule',
        tile_run: 'Run now',
        tile_stop: 'Stop',
        tile_notify: 'Notifications',
        automation: 'Run by',
        on: 'on',
        off: 'off',
        missing: 'The Annika schedule sensor was not found. Is `entity` the schedule\'s status sensor, and `pool_filter` set in the Annika configuration?',
      },
    },
    es: {
      headings: { schedule: 'Programa', timetable: 'Horarios', history: 'Historial' },
      labels: {
        next: 'Próxima corrida',
        none: 'Sin corridas programadas',
        disabled: 'Programa apagado',
        running: 'Prendida',
        until: 'hasta',
        season: 'Temporada',
        runs: 'Horarios',
        now: 'hoy',
        minutes: 'min',
        tile_schedule: 'Programa',
        tile_run: 'Ejecutar ahora',
        tile_stop: 'Detener',
        tile_notify: 'Notificaciones',
        automation: 'Lo maneja',
        on: 'prendida',
        off: 'apagada',
        missing: 'No se encontró el sensor del programa de Annika. ¿`entity` es el sensor de estado del programa, y está `pool_filter` en la configuración de Annika?',
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

  // What the card is built from. When it changes (seasons or runs edited in
  // YAML, then a restart) the card is built again; anything else is a value
  // that changes in place.
  function structureOf(attributes) {
    const { seasons, entities } = attributes
    return JSON.stringify({ seasons, entities })
  }

  function pressAction(entity) {
    return { action: 'perform-action', perform_action: 'button.press', target: { entity_id: entity } }
  }

  class AnnikaPoolFilterCard extends HTMLElement {
    setConfig(config) {
      if (!config || !config.entity) throw new Error(`${CARD}: "entity" is required`)
      this._config = config
      this._entity = config.entity
      this._texts = undefined
      this._resolveTexts()
      this._structure = this._hass ? this._structureNow() : undefined
      this._cards = undefined
      this._render()
    }

    // The tiles live inside a stock card's shadow root, out of reach of this
    // card's CSS, so their columns follow the width here: two by two on a phone.
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
      const seasons = state ? (state.attributes.seasons || []).length : 4
      return 8 + seasons * 2
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
      // The seasons or runs changed while it was building: build again.
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
      const tile = (entity, options = {}, name) => tileConfig({ entity, name, color }, options)
      const labels = this._labels

      // One row of tiles, small: the timetable's own toggle, the switch itself,
      // and the two actions. Tapping a toggle tile flips it.
      const press = (entity) => ({ hide_state: true, tap_action: pressAction(entity), icon_tap_action: pressAction(entity) })
      const scheduleCards = [headingConfig(headings.schedule)]
      // The tiles are built again when a run starts or ends: Stop while the
      // switch is running, Run now while it is not.
      this._tileConfig = (running) => {
        const columns = entities.notify ? TILE_COLUMNS : TILE_COLUMNS - 1
        return gridConfig(
          [
            // With an automation of the house's own, the toggle is that automation.
            tile(entities.automation || entities.enabled, { features: [{ type: 'toggle' }], features_position: 'inline' }, entities.automation ? undefined : labels.tile_schedule),
            tile(entities.switch),
            // A button's state is when it was last pressed: nothing worth a line.
            running
              ? tile(entities.stop, press(entities.stop), labels.tile_stop)
              : tile(entities.run, press(entities.run), labels.tile_run),
            // Only when the integration has `notify_view`: whether runs send an event.
            ...(entities.notify ? [tile(entities.notify, {}, labels.tile_notify)] : []),
          ],
          this._narrow ? NARROW_TILE_COLUMNS : columns,
        )
      }

      const historyConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig(headings.history),
          {
            type: 'history-graph',
            refresh_interval: 60,
            hours_to_show: Number(this._config.history_hours) || DEFAULT_HISTORY_HOURS,
            entities: [{ entity: entities.switch, name: attributes.friendly_name || undefined }],
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

      const column = (configs, ...extras) => {
        const element = document.createElement('div')
        element.className = 'annika-pf-column'
        for (const config of configs) element.appendChild(build(config))
        for (const extra of extras) element.appendChild(extra)
        return element
      }

      this._status = document.createElement('div')
      this._status.className = 'annika-pf-status'
      this._tilesHost = document.createElement('div')
      this._tilesRunning = this._isRunning()
      this._tileCard = build(this._tileConfig(this._tilesRunning))
      this._tilesHost.appendChild(this._tileCard)

      this.innerHTML = `
        <style>
          ${HEADING_CSS}
          ${CHECKBOX_CSS}
          ${HISTORY_CSS}
          .annika-pf-top { display: grid; grid-template-columns: 1fr; gap: 16px; align-items: start; }
          .annika-pf-top > * { min-width: 0; }
          .annika-pf-column { display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
          .annika-pf-block { margin-top: 16px; display: block; height: auto; }
          .annika-pf-status { color: var(--secondary-text-color); font-size: 14px; line-height: 1.4; padding: 4px 4px 0; }
          .annika-pf-status strong { color: var(--primary-text-color); font-weight: 500; }
          .annika-pf-table-card { padding: 8px 0; }
          .annika-pf-scroll { overflow-x: auto; }
          .annika-pf-table { border-collapse: collapse; width: 100%; font-size: 14px; }
          .annika-pf-table th, .annika-pf-table td { padding: 8px 10px; text-align: left; vertical-align: middle; }
          .annika-pf-table th { color: var(--secondary-text-color); font-weight: 500; font-size: 12px; }
          .annika-pf-table th.season, .annika-pf-table td.season { padding-left: 16px; white-space: nowrap; }
          .annika-pf-table th.minutes, .annika-pf-table td.minutes { text-align: right; padding-right: 16px; white-space: nowrap; }
          .annika-pf-table tbody tr { border-top: 1px solid var(--divider-color); }
          .annika-pf-table tr.current td.season { box-shadow: inset 3px 0 0 var(--primary-color); }
          .annika-pf-table .name { color: var(--primary-text-color); font-weight: 500; }
          .annika-pf-table .months { color: var(--secondary-text-color); font-size: 12px; }
          .annika-pf-table .now { color: var(--primary-color); font-size: 12px; margin-left: 6px; }
          .annika-pf-runs { display: flex; flex-wrap: wrap; gap: 8px 16px; }
          .annika-pf-run { display: inline-flex; align-items: center; gap: 6px; }
          .annika-pf-table input[type=number], .annika-pf-table input[type=time] {
            padding: 4px 6px; font: inherit; color: var(--primary-text-color);
            background: var(--secondary-background-color, transparent);
            border: 1px solid var(--divider-color); border-radius: 6px;
          }
          .annika-pf-table input[type=number] { width: 56px; text-align: right; }
          .annika-pf-table .unit { color: var(--secondary-text-color); font-size: 12px; margin-left: 4px; }
        </style>
      `
      const top = document.createElement('div')
      top.className = 'annika-pf-top'
      top.appendChild(column(scheduleCards, this._tilesHost, this._status))
      this.appendChild(top)

      const timetable = document.createElement('div')
      timetable.className = 'annika-pf-block annika-pf-column'
      timetable.appendChild(build(headingConfig(headings.timetable)))
      timetable.appendChild(this._table(attributes))
      this.appendChild(timetable)

      if (entities.switch) {
        const history = build(historyConfig)
        history.classList.add('annika-pf-block', 'annika-history')
        this.appendChild(history)
      }

      this._cards = cards
    }

    // The one part with no stock card: a season per row, a checkbox and a time
    // for each of its runs, and the minutes, each bound to its own entity.
    _table(attributes) {
      const hass = this._hass
      const lang = annika().language(hass, this._config)
      const month = new Intl.DateTimeFormat(lang, { month: 'short', timeZone: 'UTC' })
      const seasons = attributes.seasons || []

      const rows = seasons
        .map((season) => {
          const months = (season.months || []).map((m) => month.format(new Date(Date.UTC(2024, m - 1, 1)))).join(', ')
          const runs = (season.runs || [])
            .map((run, index) => {
              const label = `${season.name} ${index + 1}`
              return `<span class="annika-pf-run">
                <input type="checkbox" class="annika-check" data-entity="${escapeHtml(run.enabled || '')}" aria-label="${escapeHtml(label)}" ${run.enabled ? '' : 'disabled'}>
                <input type="time" data-entity="${escapeHtml(run.time || '')}" aria-label="${escapeHtml(label)}" ${run.time ? '' : 'disabled'}>
              </span>`
            })
            .join('')
          return `
            <tr data-season="${escapeHtml(season.key)}">
              <td class="season"><span class="name">${escapeHtml(season.name)}</span><span class="now" hidden>${escapeHtml(this._labels.now)}</span><div class="months">${escapeHtml(months)}</div></td>
              <td><div class="annika-pf-runs">${runs}</div></td>
              <td class="minutes"><input type="number" min="0" max="720" step="1" inputmode="numeric" data-entity="${escapeHtml(season.minutes || '')}" aria-label="${escapeHtml(`${season.name} ${this._labels.minutes}`)}" ${season.minutes ? '' : 'disabled'}><span class="unit">${escapeHtml(this._labels.minutes)}</span></td>
            </tr>`
        })
        .join('')

      const card = document.createElement('ha-card')
      card.className = 'annika-pf-table-card'
      card.innerHTML = `<div class="annika-pf-scroll"><table class="annika-pf-table"><thead><tr>
        <th class="season">${escapeHtml(this._labels.season)}</th>
        <th>${escapeHtml(this._labels.runs)}</th>
        <th class="minutes">${escapeHtml(this._labels.minutes)}</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`

      card.addEventListener('change', (event) => {
        const input = event.target
        const entity = input && input.dataset && input.dataset.entity
        if (!entity || !this._hass) return
        if (input.type === 'checkbox') {
          this._hass.callService('switch', input.checked ? 'turn_on' : 'turn_off', { entity_id: entity })
          return
        }
        if (input.type === 'time') {
          if (!/^\d{2}:\d{2}$/.test(input.value)) return this._updateInput(input, true)
          this._hass.callService('time', 'set_value', { entity_id: entity, time: `${input.value}:00` })
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
        if (event.target && (event.target.type === 'number' || event.target.type === 'time')) this._updateInput(event.target, true)
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
      if (input.type === 'time') {
        input.value = state && /^\d{2}:\d{2}/.test(state.state) ? state.state.slice(0, 5) : ''
        return
      }
      if (!state || Number.isNaN(Number(state.state))) {
        input.value = ''
        return
      }
      input.value = String(Math.round(Number(state.state)))
    }

    _isRunning() {
      const state = this._hass && this._hass.states[this._entity]
      return !!state && state.state === 'running'
    }

    // Run now and Stop take the same place: only the one that makes sense shows.
    _swapTiles() {
      const running = this._isRunning()
      if (!this._tilesHost || !this._tileConfig || running === this._tilesRunning) return
      this._tilesRunning = running
      this._tilesPending = (async () => {
        const helpers = await window.loadCardHelpers()
        const card = helpers.createCardElement(this._tileConfig(running))
        card.hass = this._hass
        if (running !== this._tilesRunning) return
        const index = this._cards ? this._cards.indexOf(this._tileCard) : -1
        if (index >= 0) this._cards[index] = card
        this._tilesHost.replaceChildren(card)
        this._tileCard = card
      })()
    }

    _update() {
      if (!this._hass || !this._tableCard) return
      const state = this._hass.states[this._entity]
      if (!state) return
      this._swapTiles()
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
    }

    _statusLine(state) {
      const labels = this._labels
      const attributes = state.attributes
      if (state.state === 'running') {
        const until = attributes.running_until ? ` · ${escapeHtml(labels.until)} ${escapeHtml(this._clock(attributes.running_until))}` : ''
        return `<strong>${escapeHtml(labels.running)}</strong>${until}`
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

    _clock(iso) {
      const hass = this._hass
      const timeZone = (hass.config && hass.config.time_zone) || undefined
      return new Intl.DateTimeFormat(annika().language(hass, this._config), { timeZone, hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
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
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaPoolFilterCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Pool Filter',
    description: 'A seasonal timetable for one switch: the runs of each season, their times and their minutes.',
  })
})()
