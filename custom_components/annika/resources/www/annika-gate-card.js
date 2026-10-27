// Annika gate card.
//
// The dashboard for the gate the Annika integration runs (see gate.py): one
// cover that opens, closes, stops and goes to a position, worked out from what
// the motor consumes, plus everything needed to check and calibrate it.
// Everything it shows comes from the integration's status sensor, whose
// attributes map the entities it created and the four it was given, so the
// card needs no entity list.
//
//   Gate: the cover (open, close, stop, position), whether the motor is
//     moving, and the calibrate button; under them, what the gate is doing and
//     the result of the last calibration.
//   Sensors: what the four source entities say right now (closed sensor, open
//     sensor, consumption, pulse relay).
//   Settings: the opening time, the closing time, the power threshold and the
//     relay's auto-off timer (read from the Shelly itself), with steppers, and
//     whether each end sensor is inverted (switches, in the same grid); with `notify_view`, whether opening and closing send an event.
//   History: the consumption and the motor over the last hours.
//
// Usage in a dashboard view:
//   type: custom:annika-gate-card
//   entity: sensor.gate         # the status sensor
//   history_hours: 6            # optional (default 6)
//   color: primary              # optional, tile color (default primary)
//   language: es                # optional; by default the Home Assistant
//                               # language (English and Spanish are built in)
//   headings:                   # optional, override single headings
//     gate: Portón
//     sensors: Sensores
//     settings: Ajustes
//     history: Historial
//   labels:                     # optional, override single texts
//     tile_moving: En movimiento
//   grid_options:
//     columns: full
;(() => {
  const CARD = 'annika-gate-card'
  const DEFAULT_HISTORY_HOURS = 6
  const DEFAULT_COLOR = 'primary'
  const NARROW_WIDTH = 640
  const TILE_COLUMNS = 3
  const NARROW_TILE_COLUMNS = 1
  const STEPPER_COLUMNS = 3

  // The card's own texts, by Home Assistant language (see Annika.textsFor in
  // annika-common.js). `headings:` and `labels:` in the card config override
  // single texts on top.
  const TEXTS = {
    en: {
      headings: { gate: 'Gate', sensors: 'Sensors', settings: 'Settings', history: 'History' },
      labels: {
        tile_moving: 'Moving',
        tile_calibrate: 'Calibrate',
        tile_closed: 'Closed sensor',
        tile_open: 'Open sensor',
        tile_power: 'Consumption',
        tile_pulse: 'Pulse relay',
        tile_open_seconds: 'Opening time',
        tile_close_seconds: 'Closing time',
        tile_threshold: 'Power threshold',
        tile_notify: 'Notifications',
        tile_auto_off: 'Relay auto-off',
        tile_closed_inverted: 'Invert closed',
        tile_open_inverted: 'Invert open',
        warn_missing: 'Not found in Home Assistant: {entities}. Check the entity ids in the Annika configuration.',
        warn_no_auto_off: 'The relay has no auto-off: if the network drops while it is on, the gate\'s input stays pressed.',
        warn_short_auto_off: 'The relay\'s auto-off cuts the pulse short: it turns off after {auto_off} s and the pulse is set to {pulse} s.',
        warn_inverted: 'Both end sensors say the gate is at its end: one of them is probably inverted.',
        fix_auto_off: 'Use {value} s',
        position: 'Position',
        status_closed: 'Closed',
        status_opening: 'Opening',
        status_open: 'Open',
        status_closing: 'Closing',
        status_stopped: 'Stopped',
        status_calibrating: 'Calibrating',
        status_unavailable: 'Unavailable',
        last_move: 'Last move',
        opening: 'opening',
        closing: 'closing',
        complete: 'complete',
        partial: 'partial',
        seconds: 's',
        calibration_running: 'Calibrating: timing a full run each way',
        calibration_ok: 'Calibrated',
        calibration_failed: 'Calibration failed',
        reason_no_closed: 'it never reached the closed sensor',
        reason_no_motion: 'the pulse did not move it',
        reason_wrong_direction: 'it went the wrong way',
        reason_never_stopped: 'it never stopped',
        reason_stopped_early: 'it stopped before the end sensor',
        reason_too_short: 'the run was too short to measure',
        reason_no_power: 'the motor drew no more than the board at rest',
        reason_cancelled: 'it was cancelled',
        unavailable: 'One of the gate\'s sensors is unavailable',
        missing: 'The Annika gate sensor was not found. Is `entity` the gate\'s status sensor, and `gate` set in the Annika configuration?',
      },
    },
    es: {
      headings: { gate: 'Portón', sensors: 'Sensores', settings: 'Ajustes', history: 'Historial' },
      labels: {
        tile_moving: 'En movimiento',
        tile_calibrate: 'Calibrar',
        tile_closed: 'Sensor de cerrado',
        tile_open: 'Sensor de abierto',
        tile_power: 'Consumo',
        tile_pulse: 'Relé de pulso',
        tile_open_seconds: 'Tiempo de apertura',
        tile_close_seconds: 'Tiempo de cierre',
        tile_threshold: 'Umbral de consumo',
        tile_notify: 'Notificaciones',
        tile_auto_off: 'Auto-off del relé',
        tile_closed_inverted: 'Invertir cerrado',
        tile_open_inverted: 'Invertir abierto',
        warn_missing: 'No se encuentran en Home Assistant: {entities}. Revisá los ids en la configuración de Annika.',
        warn_no_auto_off: 'El relé no tiene auto-off: si se cae la red mientras está activado, la entrada del portón queda apretada.',
        warn_short_auto_off: 'El auto-off del relé corta el pulso antes: se apaga a los {auto_off} s y el pulso está en {pulse} s.',
        warn_inverted: 'Los dos sensores dicen que el portón está en su extremo: probablemente uno esté invertido.',
        fix_auto_off: 'Usar {value} s',
        position: 'Posición',
        status_closed: 'Cerrado',
        status_opening: 'Abriendo',
        status_open: 'Abierto',
        status_closing: 'Cerrando',
        status_stopped: 'Detenido',
        status_calibrating: 'Calibrando',
        status_unavailable: 'No disponible',
        last_move: 'Último movimiento',
        opening: 'abriendo',
        closing: 'cerrando',
        complete: 'completo',
        partial: 'parcial',
        seconds: 's',
        calibration_running: 'Calibrando: midiendo un recorrido completo en cada sentido',
        calibration_ok: 'Calibrado',
        calibration_failed: 'Falló la calibración',
        reason_no_closed: 'no llegó al sensor de cerrado',
        reason_no_motion: 'el pulso no lo movió',
        reason_wrong_direction: 'fue en el sentido contrario',
        reason_never_stopped: 'nunca se detuvo',
        reason_stopped_early: 'se detuvo antes del sensor del extremo',
        reason_too_short: 'el recorrido fue muy corto para medirlo',
        reason_no_power: 'el motor no consumió más que la placa en reposo',
        reason_cancelled: 'se canceló',
        unavailable: 'Alguno de los sensores del portón no está disponible',
        missing: 'No se encontró el sensor del portón de Annika. ¿`entity` es el sensor de estado del portón, y está `gate` en la configuración de Annika?',
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

  // What the card is built from. When it changes (the entities map, after a
  // change in YAML and a restart) the card is built again; anything else is a
  // value that changes in place.
  function structureOf(attributes) {
    return JSON.stringify({ entities: attributes.entities })
  }

  function pressAction(entity) {
    return { action: 'perform-action', perform_action: 'button.press', target: { entity_id: entity } }
  }

  class AnnikaGateCard extends HTMLElement {
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
    // card's CSS, so their columns follow the width here.
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
      return 14
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
      if (this._structureNow() !== built) {
        this._cards = undefined
        return this._render()
      }
      this._update()
    }

    async _build(attributes) {
      const { tileConfig, headingConfig, gridConfig, HEADING_CSS, HISTORY_CSS } = annika()
      const helpers = await window.loadCardHelpers()
      const entities = attributes.entities || {}
      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color
      const headings = this._headings
      const labels = this._labels
      const tile = (entity, options = {}, name) => tileConfig({ entity, name, color }, options)
      const readOnly = { tap_action: { action: 'more-info' }, icon_tap_action: { action: 'more-info' } }
      const present = (configs) => configs.filter((config) => config.entity)
      const columns = this._narrow ? NARROW_TILE_COLUMNS : TILE_COLUMNS

      // The cover is the gate: its own open, close and stop buttons and its
      // position slider, as in any Home Assistant dashboard.
      const gateCards = [
        headingConfig(headings.gate),
        gridConfig(
          present([
            tile(entities.cover, { features: [{ type: 'cover-open-close' }, { type: 'cover-position' }], features_position: 'bottom' }),
            tile(entities.moving, {}, labels.tile_moving),
            tile(entities.calibrate, { hide_state: true, tap_action: pressAction(entities.calibrate), icon_tap_action: pressAction(entities.calibrate) }, labels.tile_calibrate),
          ]),
          columns,
        ),
      ]

      // What the four entities the gate was given say, as native tiles: the
      // point is to open the card and see what the sensors are reporting.
      const sensorCards = [
        headingConfig(headings.sensors),
        gridConfig(
          present([
            // These only report: a sensor that is a switch (a Shelly Uni input) must not toggle when tapped.
            tile(entities.closed, readOnly, labels.tile_closed),
            tile(entities.open, readOnly, labels.tile_open),
            tile(entities.power, readOnly, labels.tile_power),
            tile(entities.pulse, readOnly, labels.tile_pulse),
          ]),
          this._narrow ? 2 : 4,
        ),
      ]

      const stepper = (entity, name) => tile(entity, { features: [{ type: 'numeric-input', style: 'buttons' }] }, name)
      const settingTiles = present([
        stepper(entities.open_seconds, labels.tile_open_seconds),
        stepper(entities.close_seconds, labels.tile_close_seconds),
        stepper(entities.threshold, labels.tile_threshold),
        stepper(entities.auto_off, labels.tile_auto_off),
      ])
      // Whether each end sensor reads the other way round: a setting, next to the sensors' own tiles above.
      settingTiles.push(...present([
        tile(entities.closed_inverted, {}, labels.tile_closed_inverted),
        tile(entities.open_inverted, {}, labels.tile_open_inverted),
      ]))
      if (entities.notify) settingTiles.push(tile(entities.notify, {}, labels.tile_notify))
      const settingCards = [
        headingConfig(headings.settings),
        gridConfig(settingTiles, this._narrow ? NARROW_TILE_COLUMNS : STEPPER_COLUMNS + 1),
      ]

      const historyEntities = [entities.power, entities.moving, entities.cover].filter(Boolean).map((entity) => ({ entity }))
      const historyConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig(headings.history),
          {
            type: 'history-graph',
            refresh_interval: 60,
            hours_to_show: Number(this._config.history_hours) || DEFAULT_HISTORY_HOURS,
            entities: historyEntities,
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
        element.className = 'annika-gate-column'
        for (const config of configs) element.appendChild(build(config))
        for (const extra of extras) element.appendChild(extra)
        return element
      }

      this._status = document.createElement('div')
      this._status.className = 'annika-gate-status'
      this._status.addEventListener('click', (event) => {
        const button = event.target && event.target.closest && event.target.closest('button[data-entity]')
        if (!button || !this._hass) return
        this._hass.callService('number', 'set_value', { entity_id: button.dataset.entity, value: Number(button.dataset.value) })
      })

      this.innerHTML = `
        <style>
          ${HEADING_CSS}
          ${HISTORY_CSS}
          .annika-gate-column { display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
          .annika-gate-block { margin-top: 16px; display: block; height: auto; }
          .annika-gate-status { color: var(--secondary-text-color); font-size: 14px; line-height: 1.5; padding: 4px 4px 0; }
          .annika-gate-status strong { color: var(--primary-text-color); font-weight: 500; }
          .annika-gate-status .failed { color: var(--error-color); }
          .annika-gate-status .warn { color: var(--warning-color, #ffa600); }
          .annika-gate-status button {
            margin-left: 8px; padding: 2px 10px; font: inherit; font-size: 12px; cursor: pointer;
            color: var(--primary-color); background: transparent;
            border: 1px solid var(--primary-color); border-radius: 12px;
          }
          .annika-gate-status div + div { margin-top: 2px; }
        </style>
      `
      this.appendChild(column(gateCards, this._status))

      const sensors = column(sensorCards)
      sensors.classList.add('annika-gate-block')
      this.appendChild(sensors)

      const settings = column(settingCards)
      settings.classList.add('annika-gate-block')
      this.appendChild(settings)

      if (historyEntities.length) {
        const history = build(historyConfig)
        history.classList.add('annika-gate-block', 'annika-history')
        this.appendChild(history)
      }

      this._cards = cards
    }

    _update() {
      if (!this._hass || !this._status) return
      const state = this._hass.states[this._entity]
      if (!state) return
      this._status.innerHTML = this._statusLines(state)
    }

    _statusLines(state) {
      const labels = this._labels
      const attributes = state.attributes
      const lines = []

      // The cover moves every second; the sensor's own position only when something changes.
      const cover = this._hass.states[(attributes.entities || {}).cover]
      const live = cover && cover.attributes.current_position
      const position = Number(live === undefined || live === null ? attributes.position : live)
      const label = labels[`status_${state.state}`] || state.state
      const head = Number.isNaN(position) ? `<strong>${escapeHtml(label)}</strong>` : `<strong>${escapeHtml(label)}</strong> · ${escapeHtml(labels.position)} ${Math.round(position)}%`
      lines.push(`<div>${head}</div>`)

      if (state.state === 'unavailable') lines.push(`<div class="failed">${escapeHtml(labels.unavailable)}</div>`)

      const move = attributes.last_move
      if (move) {
        const direction = move.direction === 'opening' ? labels.opening : labels.closing
        const kind = move.complete ? labels.complete : labels.partial
        lines.push(
          `<div>${escapeHtml(labels.last_move)}: <strong>${escapeHtml(direction)}</strong> · ${escapeHtml(String(move.seconds))} ${escapeHtml(labels.seconds)} · ${Math.round(move.from)}% → ${Math.round(move.to)}% · ${escapeHtml(kind)}</div>`,
        )
      }

      lines.push(...this._warnings(attributes))

      const calibration = attributes.calibration || {}
      if (calibration.status === 'running') {
        lines.push(`<div><strong>${escapeHtml(labels.calibration_running)}</strong></div>`)
      } else if (calibration.status === 'ok') {
        lines.push(
          `<div>${escapeHtml(labels.calibration_ok)}: ${escapeHtml(labels.tile_open_seconds.toLowerCase())} <strong>${escapeHtml(String(calibration.open_seconds))} ${escapeHtml(labels.seconds)}</strong> · ${escapeHtml(labels.tile_close_seconds.toLowerCase())} <strong>${escapeHtml(String(calibration.close_seconds))} ${escapeHtml(labels.seconds)}</strong> · ${escapeHtml(labels.tile_threshold.toLowerCase())} <strong>${escapeHtml(String(calibration.threshold))} W</strong></div>`,
        )
      } else if (calibration.status === 'failed') {
        const reason = labels[`reason_${calibration.message}`] || calibration.message || ''
        lines.push(`<div class="failed">${escapeHtml(labels.calibration_failed)}: ${escapeHtml(reason)}</div>`)
      }
      return lines.join('')
    }

    // Two things worth fixing before trusting the gate: a relay with no auto-off
    // (or one that cuts the pulse short), and end sensors that cannot both be right.
    _warnings(attributes) {
      const labels = this._labels
      const entities = attributes.entities || {}
      const warnings = []

      // The gate can do nothing sensible without its four entities: say which ones Home Assistant does not know.
      const missing = ['pulse', 'power', 'closed', 'open'].map((key) => entities[key]).filter((id) => id && !this._hass.states[id])
      if (missing.length) {
        warnings.push(`<div class="failed">${escapeHtml(labels.warn_missing.replace('{entities}', missing.join(', ')))}</div>`)
      }

      const autoOff = this._hass.states[entities.auto_off]
      if (autoOff && autoOff.state !== 'unavailable' && autoOff.state !== 'unknown') {
        const seconds = Number(autoOff.state)
        const pulse = Number(attributes.pulse_seconds) || 0
        const recommended = Math.max(1, Math.ceil(pulse * 20) / 10)
        const fix = `<button type="button" data-entity="${escapeHtml(entities.auto_off)}" data-value="${recommended}">${escapeHtml(labels.fix_auto_off.replace('{value}', recommended))}</button>`
        if (seconds === 0) {
          warnings.push(`<div class="warn">${escapeHtml(labels.warn_no_auto_off)}${fix}</div>`)
        } else if (seconds < pulse) {
          const text = labels.warn_short_auto_off.replace('{auto_off}', seconds).replace('{pulse}', pulse)
          warnings.push(`<div class="warn">${escapeHtml(text)}${fix}</div>`)
        }
      }

      if (attributes.closed && attributes.open) warnings.push(`<div class="warn">${escapeHtml(labels.warn_inverted)}</div>`)
      return warnings
    }
  }

  // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaGateCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Gate',
    description: 'The gate: open, close, stop, where it is, what its sensors say, and calibration.',
  })
})()
