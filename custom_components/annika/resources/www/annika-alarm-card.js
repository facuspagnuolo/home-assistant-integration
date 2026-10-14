// Annika alarm card: the whole alarm of a unit on one screen.
//
//   - A keypad to arm, disarm and change the code of Annika's own alarm panel
//     (the `alarm:` block of the integration, see alarm_panel.py). Disarm only
//     exists while the alarm is doing something; "Change code" walks three
//     steps: the current code, the new one, the new one again.
//   - Warning: how many warnings before a trigger, and the quiet minutes that
//     start the count over, with where the count stands right now.
//   - What fires: which outputs a warning and a trigger switch on, and for how
//     long. A play button runs each one so it can be heard and seen.
//   - Zones and sensors: what each zone — and, when it needs its own rule, each
//     sensor — does in every mode: off, warning or trigger.
//   - Automations: arming and disarming by itself, with the mode it arms in.
//   - Activity: why the alarm did what it did, newest first.
//
// Everything it shows comes from attributes of the panel entity, so the card
// needs nothing but the entity. See alarm_rules.py and alarm_panel.py.
//
// Usage in a dashboard view:
//   type: custom:annika-alarm-card
//   entity: alarm_control_panel.home_alarm
//   name: Alarm                 # optional
//   language: es                # optional; by default the Home Assistant language
//   grid_options:
//     columns: full

;(() => {
  const CARD = 'annika-alarm-card'

  const TEXTS = {
    en: {
      disarmed: 'Disarmed',
      arming: 'Arming',
      armed_away: 'Armed away',
      armed_night: 'Armed night',
      armed_vacation: 'Armed vacation',
      pending: 'Intruder? Disarm now',
      triggered: 'Triggered',
      disarm: 'Disarm',
      arm_away: 'Arm away',
      arm_night: 'Arm night',
      arm_vacation: 'Arm vacation',
      enter_arm: 'Enter the code to arm',
      enter_disarm: 'Enter the code to disarm',
      choose: 'Choose a mode',
      change_code: 'Change code',
      cancel: 'Cancel',
      step_current: 'Current code',
      step_new: 'New code',
      step_repeat: 'Repeat the new code',
      step_of: 'Step {n} of 3',
      mismatch: "The codes don't match",
      changed: 'Code changed',
      locked: 'Keypad locked. Try again in {minutes} min',
      missing: 'Entity not found: {entity}',
      remaining: '{seconds} s',
      warning: 'Warning',
      warnings_before: 'Warnings before trigger',
      counter_resets: 'Counter resets after',
      without_detections: 'min without detections',
      now: 'Now {n} of {limit}',
      resets_in: 'resets in {minutes} min',
      what_fires: 'What fires',
      arming: 'Arming',
      arming_time: 'Arming time',
      delay_time: 'Delay time',
      arming_hint: 'Seconds to leave before the alarm is armed',
      delay_hint: 'Seconds to disarm after something trips the alarm',
      device: 'Device',
      on_warning: 'On warning',
      on_trigger: 'On trigger',
      test: 'Test',
      sec: 'sec',
      min: 'min',
      until_disarmed: 'until disarmed',
      stop: 'Stop',
      notification: 'Notification',
      notification_sub: 'Annika app · view: {view}',
      entities_sub: '{n} entities',
      zones: 'Zones and sensors',
      zone_sensor: 'Zone / sensor',
      mode_away: 'Away',
      mode_night: 'Night',
      mode_vacation: 'Vacation',
      rule_off: 'Off',
      rule_warning: 'Warning',
      rule_trigger: 'Trigger',
      sensors_n: '{n} sensors',
      sensors_1: '1 sensor',
      own_rule: 'overwritten',
      decisions: 'Activity',
      no_decisions: 'Nothing yet',
      yesterday: 'Yesterday',
      auto_title: 'Automations',
      auto_arm: 'Arm automatically',
      auto_disarm: 'Disarm automatically',
      at: 'at',
      in_mode: 'in mode',
      quiet: 'once no sensor has been active for',
      minutes: 'min',
      waiting: 'Waiting for the house to go quiet',
    },
    es: {
      disarmed: 'Desarmada',
      arming: 'Armando',
      armed_away: 'Armada afuera',
      armed_night: 'Armada noche',
      armed_vacation: 'Armada vacaciones',
      pending: '¿Intruso? Desarmá ahora',
      triggered: 'Disparada',
      disarm: 'Desarmar',
      arm_away: 'Armar afuera',
      arm_night: 'Armar noche',
      arm_vacation: 'Armar vacaciones',
      enter_arm: 'Ingresá el código para armar',
      enter_disarm: 'Ingresá el código para desarmar',
      choose: 'Elegí un modo',
      change_code: 'Cambiar código',
      cancel: 'Cancelar',
      step_current: 'Código actual',
      step_new: 'Código nuevo',
      step_repeat: 'Repetí el código nuevo',
      step_of: 'Paso {n} de 3',
      mismatch: 'Los códigos no coinciden',
      changed: 'Código cambiado',
      locked: 'Teclado bloqueado. Probá de nuevo en {minutes} min',
      missing: 'No se encontró la entidad: {entity}',
      remaining: '{seconds} s',
      warning: 'Aviso',
      warnings_before: 'Avisos antes del disparo',
      counter_resets: 'El contador se reinicia a los',
      without_detections: 'min sin detecciones',
      now: 'Ahora {n} de {limit}',
      resets_in: 'se reinicia en {minutes} min',
      what_fires: 'Qué se activa',
      arming: 'Armado',
      arming_time: 'Tiempo de armado',
      delay_time: 'Tiempo de demora',
      arming_hint: 'Segundos para salir antes de que la alarma quede armada',
      delay_hint: 'Segundos para desarmar después de que algo la dispara',
      device: 'Dispositivo',
      on_warning: 'En aviso',
      on_trigger: 'En disparo',
      test: 'Probar',
      sec: 'seg',
      min: 'min',
      until_disarmed: 'hasta desarmar',
      stop: 'Detener',
      notification: 'Notificación',
      notification_sub: 'App Annika · vista: {view}',
      entities_sub: '{n} entidades',
      zones: 'Zonas y sensores',
      zone_sensor: 'Zona / sensor',
      mode_away: 'Afuera',
      mode_night: 'Noche',
      mode_vacation: 'Vacaciones',
      rule_off: 'Apagado',
      rule_warning: 'Aviso',
      rule_trigger: 'Disparo',
      sensors_n: '{n} sensores',
      sensors_1: '1 sensor',
      own_rule: 'sobrescrita',
      decisions: 'Actividad',
      no_decisions: 'Todavía nada',
      yesterday: 'Ayer',
      auto_title: 'Automatizaciones',
      auto_arm: 'Armar automáticamente',
      auto_disarm: 'Desarmar automáticamente',
      at: 'a las',
      in_mode: 'en modo',
      quiet: 'cuando ningún sensor estuvo activo por',
      minutes: 'min',
      waiting: 'Esperando a que la casa se quede en calma',
    },
  }

  const MODES = ['away', 'night', 'vacation']
  const RULES = ['off', 'warning', 'trigger']
  const ARM = ['arm_away', 'arm_night', 'arm_vacation']
  const MAX_CODE = 8
  const STEPS = ['step_current', 'step_new', 'step_repeat']
  const SERVICE_DOMAIN = 'annika'

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')

  const STOP = '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M6 6h12v12H6z"/></svg>'
  const PLAY = '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>'

  class AnnikaAlarmCard extends HTMLElement {
    setConfig(config) {
      this._config = config
      this._code = ''
      this._action = null // arm_away | arm_night | arm_vacation | null
      this._change = null // null, or { step, current, next }
      this._error = ''
      this._notice = ''
      this._busy = false
      this._structure = ''
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      this._render()
      this._updateSensors()
    }

    getCardSize() {
      return 12
    }

    // The entity of the card, or the Annika panel when none is set: the one
    // alarm_control_panel that carries the panel's modes. A card added from the
    // dashboard picker works with no configuration.
    get _entity() {
      const wanted = this._config && this._config.entity
      if (wanted) return wanted
      const states = (this._hass && this._hass.states) || {}
      return Object.keys(states).find(
        (id) => id.startsWith('alarm_control_panel.') && states[id].attributes && states[id].attributes.modes
      )
    }

    getGridOptions() {
      return { columns: 'full' }
    }

    getLayoutOptions() {
      return { grid_columns: 'full' }
    }

    static getStubConfig(hass) {
      const states = (hass && hass.states) || {}
      const entity = Object.keys(states).find(
        (id) => id.startsWith('alarm_control_panel.') && states[id].attributes && states[id].attributes.modes
      )
      return entity ? { entity } : {}
    }

    connectedCallback() {
      this._timer = setInterval(() => this._tick(), 1000)
    }

    disconnectedCallback() {
      clearInterval(this._timer)
    }

    get _texts() {
      const lang = (window.Annika && window.Annika.language)
        ? window.Annika.language(this._hass, this._config)
        : (this._config.language || (this._hass && this._hass.language) || 'en')
      const base = String(lang).toLowerCase().split('-')[0]
      return { ...TEXTS.en, ...(TEXTS[base] || {}) }
    }

    get _stateObj() {
      return this._hass && this._hass.states[this._entity]
    }

    _service(service, data) {
      return this._hass.callService(SERVICE_DOMAIN, service, { entity_id: this._entity, ...data })
    }

    _tick() {
      const countdown = this.querySelector('[data-countdown]')
      if (countdown) countdown.textContent = this._countdown()
      const resets = this.querySelector('[data-resets]')
      if (resets) resets.textContent = this._resetsText() ? ` · ${this._resetsText()}` : ''
    }

    _countdown() {
      const deadline = this._stateObj && this._stateObj.attributes.deadline
      if (!deadline) return ''
      const seconds = Math.max(0, Math.ceil((new Date(deadline) - Date.now()) / 1000))
      return fill(this._texts.remaining, { seconds })
    }

    _resetsText() {
      const warning = this._stateObj && this._stateObj.attributes.config && this._stateObj.attributes.config.warning
      if (!warning || !warning.resets_at) return ''
      const minutes = Math.max(1, Math.ceil((new Date(warning.resets_at) - Date.now()) / 60000))
      return fill(this._texts.resets_in, { minutes })
    }

    _lockedMinutes() {
      const until = this._stateObj && this._stateObj.attributes.locked_until
      if (!until) return 0
      const ms = new Date(until) - Date.now()
      return ms > 0 ? Math.max(1, Math.ceil(ms / 60000)) : 0
    }

    // --- keypad actions ---------------------------------------------------

    _press(key) {
      if (this._busy || this._lockedMinutes()) return
      this._error = ''
      this._notice = ''
      if (key === 'back') this._code = this._code.slice(0, -1)
      else if (key === 'ok') return this._confirm()
      else if (this._code.length < MAX_CODE) this._code += key
      this._render(true)
    }

    async _confirm() {
      const code = this._code
      if (!code) return
      const state = this._stateObj.state
      this._busy = true
      try {
        if (this._change) await this._confirmChange(code)
        else if (state !== 'disarmed') {
          await this._hass.callService('alarm_control_panel', 'alarm_disarm', { entity_id: this._entity, code })
          this._code = ''
        } else if (this._action) {
          await this._hass.callService('alarm_control_panel', `alarm_${this._action}`, { entity_id: this._entity, code })
          this._code = ''
          this._action = null
        }
      } catch (err) {
        this._error = (err && err.message) || String(err)
        this._code = ''
      }
      this._busy = false
      this._render(true)
    }

    async _confirmChange(code) {
      const change = this._change
      if (change.step === 0) {
        change.current = code
        change.step = 1
      } else if (change.step === 1) {
        change.next = code
        change.step = 2
      } else if (code !== change.next) {
        this._error = this._texts.mismatch
        change.step = 1
        change.next = ''
      } else {
        await this._service('change_code', { current_code: change.current, new_code: change.next })
        this._change = null
        this._notice = this._texts.changed
      }
      this._code = ''
    }

    _startChange() {
      this._change = { step: 0, current: '', next: '' }
      this._code = ''
      this._error = ''
      this._notice = ''
      this._action = null
      this._render(true)
    }

    _cancelChange() {
      this._change = null
      this._code = ''
      this._error = ''
      this._render(true)
    }

    _chooseMode(mode) {
      this._action = this._action === mode ? null : mode
      this._error = ''
      this._render(true)
    }

    // --- rendering: pieces ------------------------------------------------

    _entityState(entityId) {
      return entityId && this._hass.states[entityId] ? this._hass.states[entityId].state : undefined
    }

    _keypadHtml(stateObj, t) {
      const state = stateObj.state
      const locked = this._lockedMinutes()
      const disarmed = state === 'disarmed'
      const heading = this._config.name || stateObj.attributes.friendly_name || 'Alarm'
      // Disarm exists only while there is something to disarm.
      const modes = disarmed && !this._change
        ? ARM.map((mode) => `<button class="mode${this._action === mode ? ' on' : ''}" data-mode="${mode}">${escapeHtml(t[mode])}</button>`).join('')
        : ''
      const disarmButton = !disarmed && !this._change
        ? `<span class="mode disarm on">${escapeHtml(t.disarm)}</span>`
        : ''

      let prompt = t.choose
      if (this._change) prompt = `${t[STEPS[this._change.step]]} · ${fill(t.step_of, { n: this._change.step + 1 })}`
      else if (!disarmed) prompt = t.enter_disarm
      else if (this._action) prompt = t.enter_arm

      const dots = Array.from({ length: Math.max(4, this._code.length) }, (_, i) => `<span class="dot${i < this._code.length ? ' full' : ''}"></span>`).join('')
      const pad = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'back', '0', 'ok']
        .map((k) => {
          const label = k === 'back' ? '⌫' : k === 'ok' ? '✓' : k
          return `<button class="key${k === 'ok' ? ' ok' : ''}${k === 'back' ? ' back' : ''}" data-key="${k}"${locked ? ' disabled' : ''}>${label}</button>`
        })
        .join('')

      const message = locked
        ? `<div class="msg error">${escapeHtml(fill(t.locked, { minutes: locked }))}</div>`
        : this._error
          ? `<div class="msg error">${escapeHtml(this._error)}</div>`
          : this._notice
            ? `<div class="msg ok">${escapeHtml(this._notice)}</div>`
            : '<div class="msg"></div>'

      const countdown = state === 'arming' || state === 'pending'
        ? `<span class="count" data-countdown="1">${escapeHtml(this._countdown())}</span>`
        : ''
      const footer = this._change
        ? `<button class="link" data-cancel="1">${escapeHtml(t.cancel)}</button>`
        : `<button class="link" data-change="1">${escapeHtml(t.change_code)}</button>`

      return `
        <ha-card class="keypad">
          <div class="annika-ak">
            <div class="top">
              <span class="name">${escapeHtml(heading)}</span>
              <span class="chip ${state.startsWith('armed') ? 'armed' : state}">${escapeHtml(t[state] || state)} ${countdown}</span>
            </div>
            <div class="modes">${modes}${disarmButton}</div>
            <div class="prompt">${escapeHtml(prompt)}</div>
            <div class="dots">${dots}</div>
            <div class="pad">${pad}</div>
            ${message}
            ${footer}
          </div>
        </ha-card>`
    }

    _warningHtml(config, t) {
      const w = config.warning
      const resets = this._resetsText()
      return `
        <h3 class="sec">${escapeHtml(t.warning)}</h3>
        <div class="panel">
        <div class="warning">
          <label class="field"><span>${escapeHtml(t.warnings_before)}</span>
            <input type="number" min="1" max="20" data-warning="limit" value="${w.limit}"></label>
          <label class="field"><span>${escapeHtml(t.counter_resets)}</span>
            <input type="number" min="1" max="1440" data-warning="window_minutes" value="${w.window_minutes}">
            <span class="muted">${escapeHtml(t.without_detections)}</span></label>
        </div>
        <div class="now">${escapeHtml(fill(t.now, { n: w.count, limit: w.limit }))}<span data-resets="1">${resets ? ` · ${escapeHtml(resets)}` : ''}</span></div>
        </div>`
    }

    _firesHtml(config, t) {
      const check = (attrs, on) => `<input type="checkbox" class="annika-check" ${attrs}${on ? ' checked' : ''}>`
      const rows = config.outputs.map((o) => {
        const minutes = o.warning_seconds >= 60 && o.warning_seconds % 60 === 0
        const value = minutes ? o.warning_seconds / 60 : o.warning_seconds
        const sub = o.entities.length === 1 ? o.entities[0] : fill(t.entities_sub, { n: o.entities.length })
        const duration = o.warning_enabled
          ? `<input type="number" min="1" data-duration="${escapeHtml(o.id)}" value="${value}">
             <select data-unit="${escapeHtml(o.id)}"><option value="1"${minutes ? '' : ' selected'}>${escapeHtml(t.sec)}</option><option value="60"${minutes ? ' selected' : ''}>${escapeHtml(t.min)}</option></select>`
          : ''
        return `<tr>
          <td class="device"><div>${escapeHtml(o.name)}</div><div class="sub">${escapeHtml(sub)}</div></td>
          <td><div class="cell">${check(`data-out-warning="${escapeHtml(o.id)}"`, o.warning_enabled)}${duration}</div></td>
          <td><div class="cell">${check(`data-out-trigger="${escapeHtml(o.id)}"`, o.trigger_enabled)}<span class="muted">${escapeHtml(t.until_disarmed)}</span></div></td>
          <td class="test"><button class="play${o.on ? ' running' : ''}" data-test="${escapeHtml(o.id)}" aria-label="${escapeHtml(o.on ? t.stop : t.test)}">${o.on ? STOP : PLAY}</button></td>
        </tr>`
      })
      const n = config.notification
      if (n.enabled) {
        rows.push(`<tr>
          <td class="device"><div>${escapeHtml(t.notification)}</div><div class="sub">${escapeHtml(fill(t.notification_sub, { view: n.view }))}</div></td>
          <td><div class="cell">${check('data-notify="warning"', n.warning)}</div></td>
          <td><div class="cell">${check('data-notify="trigger"', n.trigger)}</div></td>
          <td class="test"><button class="play" data-test="notification" aria-label="${escapeHtml(t.test)}">${PLAY}</button></td>
        </tr>`)
      }
      return `
        <h3 class="sec">${escapeHtml(t.what_fires)}</h3>
        <div class="panel table"><table class="fires">
          <thead><tr><th>${escapeHtml(t.device)}</th><th>${escapeHtml(t.on_warning)}</th><th>${escapeHtml(t.on_trigger)}</th><th class="test">${escapeHtml(t.test)}</th></tr></thead>
          <tbody>${rows.join('')}</tbody></table></div>`
    }

    _armingHtml(modes, t) {
      const rows = MODES.filter((mode) => modes[mode]).map((mode) => `<tr>
        <td class="device">${escapeHtml(t['mode_' + mode])}</td>
        <td><div class="cell"><input type="number" min="0" max="600" data-timing="${mode}" data-key="arming" value="${modes[mode].arming}"><span class="muted">${escapeHtml(t.sec)}</span></div></td>
        <td><div class="cell"><input type="number" min="0" max="600" data-timing="${mode}" data-key="pending" value="${modes[mode].pending}"><span class="muted">${escapeHtml(t.sec)}</span></div></td>
      </tr>`).join('')
      return `
        <h3 class="sec">${escapeHtml(t.arming)}</h3>
        <div class="panel table"><table class="arming">
          <thead><tr><th></th><th title="${escapeHtml(t.arming_hint)}">${escapeHtml(t.arming_time)}</th><th title="${escapeHtml(t.delay_hint)}">${escapeHtml(t.delay_time)}</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`
    }

    _zonesHtml(config, t) {
      const optionList = (selected, inherited) => {
        const options = RULES.map((rule) => `<option value="${rule}"${selected === rule ? ' selected' : ''}>${escapeHtml(t['rule_' + rule])}</option>`)
        if (inherited !== undefined) {
          options.unshift(`<option value=""${selected === null ? ' selected' : ''}>${escapeHtml(t['rule_' + inherited])}</option>`)
        }
        return options.join('')
      }
      const rows = []
      for (const zone of config.zones) {
        const summary = zone.sensors.length === 1 ? t.sensors_1 : fill(t.sensors_n, { n: zone.sensors.length })
        rows.push(`<tr class="zone"><td class="name"><b>${escapeHtml(zone.name)}</b> <span class="sub">${escapeHtml(summary)}</span></td>
          ${MODES.map((mode) => `<td><select class="rule ${zone.rules[mode]}" data-zone="${escapeHtml(zone.id)}" data-mode="${mode}">${optionList(zone.rules[mode])}</select></td>`).join('')}</tr>`)
        for (const sensor of zone.sensors) {
          const own = MODES.some((mode) => sensor.rules[mode] !== null)
          rows.push(`<tr class="sensor"><td class="name"><div class="sname">${this._sensorIcon(sensor)}<div>
            <div>${escapeHtml(sensor.name)}</div>
            <div class="sub">${escapeHtml(sensor.detail || '')}${own ? ` <span class="own">${escapeHtml(t.own_rule)}</span>` : ''}</div></div></div></td>
            ${MODES.map((mode) => {
              const selected = sensor.rules[mode]
              const effective = selected || zone.rules[mode]
              return `<td><select class="rule ${effective}${selected === null ? ' inherit' : ''}" data-sensor="${escapeHtml(sensor.id)}" data-mode="${mode}">${optionList(selected, zone.rules[mode])}</select></td>`
            }).join('')}</tr>`)
        }
      }
      return `
        <h3 class="sec wide">${escapeHtml(t.zones)}</h3>
        <div class="panel table wide"><table class="zones">
          <thead><tr><th>${escapeHtml(t.zone_sensor)}</th>${MODES.map((mode) => `<th>${escapeHtml(t['mode_' + mode])}</th>`).join('')}</tr></thead>
          <tbody>${rows.join('')}</tbody></table></div>`
    }

    // A sensor's symbol, lit green while any entity it watches is detecting.
    _sensorIcon(sensor) {
      const entities = sensor.entities || []
      const first = entities[0] && this._hass.states[entities[0]]
      const doorLike = ['door', 'window', 'garage_door', 'opening'].includes(first && first.attributes.device_class)
      const on = entities.some((id) => this._entityState(id) === 'on')
      return `<ha-icon class="sicon${on ? ' on' : ''}" icon="${doorLike ? 'mdi:door' : 'mdi:motion-sensor'}" data-watch="${escapeHtml(entities.join(','))}"></ha-icon>`
    }

    // Lights and unlights the sensor symbols in place: a detection is not worth rebuilding the card.
    _updateSensors() {
      this.querySelectorAll('.sicon[data-watch]').forEach((el) => {
        const on = el.dataset.watch.split(',').some((id) => this._entityState(id) === 'on')
        el.classList.toggle('on', on)
      })
    }

    _timeText(iso, t) {
      const date = new Date(iso)
      const clock = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
      return date.toDateString() === new Date().toDateString() ? clock : `${t.yesterday} ${clock}`
    }

    _decisionsHtml(decisions, t) {
      const rows = decisions.length
        ? decisions.map((d) => `<div class="decision"><span class="level ${escapeHtml(d.level)}"></span>
            <span class="text">${escapeHtml(d.text)}</span><span class="time">${escapeHtml(this._timeText(d.time, t))}</span></div>`).join('')
        : `<div class="decision"><span class="muted">${escapeHtml(t.no_decisions)}</span></div>`
      return `<h3 class="sec wide">${escapeHtml(t.decisions)}</h3><div class="panel decisions wide">${rows}</div>`
    }

    // The automatic arming and disarming: every setting is an entity the
    // integration made, found through the panel's `auto` attribute.
    _autoHtml(stateObj, t) {
      const auto = stateObj.attributes.auto || {}
      if (!auto.arm && !auto.disarm) return ''
      const clock = (entityId) => {
        const value = this._entityState(entityId)
        return value && value.includes(':') ? value.slice(0, 5) : ''
      }
      const check = (entityId) => `<input type="checkbox" class="annika-check" data-switch="${escapeHtml(entityId || '')}"${this._entityState(entityId) === 'on' ? ' checked' : ''}>`
      let html = `<h3 class="sec wide">${escapeHtml(t.auto_title)}</h3><div class="panel auto wide">`
      if (auto.arm) {
        const a = auto.arm
        const minutes = this._entityState(a.quiet_minutes) ?? ''
        const mode = this._entityState(a.mode_entity) || a.mode
        const modeControl = a.mode_entity
          ? `<select data-select="${escapeHtml(a.mode_entity)}">${MODES.map((m) => `<option value="${m}"${m === mode ? ' selected' : ''}>${escapeHtml(t['mode_' + m])}</option>`).join('')}</select>`
          : `<b>${escapeHtml(t['mode_' + mode] || mode)}</b>`
        const quiet = a.has_sensors
          ? `<span class="quiet">${escapeHtml(t.quiet)}</span>
             <input type="number" min="0" max="240" data-number="${escapeHtml(a.quiet_minutes || '')}" value="${escapeHtml(minutes)}"><span>${escapeHtml(t.minutes)}</span>`
          : ''
        html += `<div class="auto-row">${check(a.enabled)}<span>${escapeHtml(t.auto_arm)} ${escapeHtml(t.at)}</span>
          <input type="time" data-time="${escapeHtml(a.time || '')}" value="${clock(a.time)}">
          <span>${escapeHtml(t.in_mode)}</span>${modeControl}${quiet}</div>`
        if (a.waiting) html += `<div class="auto-row sub waiting">${escapeHtml(t.waiting)}</div>`
      }
      if (auto.disarm) {
        const d = auto.disarm
        const dMode = this._entityState(d.mode_entity) || d.mode
        const dModeControl = d.mode_entity
          ? `<select data-select="${escapeHtml(d.mode_entity)}">${MODES.map((m) => `<option value="${m}"${m === dMode ? ' selected' : ''}>${escapeHtml(t['mode_' + m])}</option>`).join('')}</select>`
          : `<b>${escapeHtml(t['mode_' + dMode] || dMode)}</b>`
        html += `<div class="auto-row">${check(d.enabled)}<span>${escapeHtml(t.auto_disarm)} ${escapeHtml(t.at)}</span>
          <input type="time" data-time="${escapeHtml(d.time || '')}" value="${clock(d.time)}">
          <span>${escapeHtml(t.in_mode)}</span>${dModeControl}</div>`
      }
      return html + '</div>'
    }

    _autoKey(stateObj) {
      const auto = stateObj.attributes.auto || {}
      const ids = []
      for (const part of [auto.arm, auto.disarm]) {
        if (part) ids.push(part.enabled, part.time, part.quiet_minutes, part.mode_entity)
      }
      return ids.filter(Boolean).map((id) => this._entityState(id)).join(',') + JSON.stringify(auto)
    }

    // --- rendering --------------------------------------------------------

    _render(force) {
      if (!this._config) return
      const stateObj = this._stateObj
      const t = this._texts
      if (!stateObj) {
        this.innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(fill(t.missing, { entity: this._entity }))}</div></ha-card>`
        this._structure = ''
        return
      }
      const attrs = stateObj.attributes
      const key = JSON.stringify([
        stateObj.state, attrs.mode, attrs.locked_until, attrs.config, attrs.modes, attrs.decisions,
        this._action, this._change && this._change.step, this._code.length, this._error, this._notice,
        this._busy, t.disarm, this._autoKey(stateObj),
      ])
      if (!force && key === this._structure) return
      this._structure = key

      const config = attrs.config
      const side = `<div class="side">${config ? this._warningHtml(config, t) + this._firesHtml(config, t) : ''}${attrs.modes ? this._armingHtml(attrs.modes, t) : ''}</div>`
      const zones = config && config.zones.length ? this._zonesHtml(config, t) : ''
      const activity = config ? this._decisionsHtml(attrs.decisions || [], t) : ''

      this.innerHTML = `
        <style>
          annika-alarm-card { display: block; container-type: inline-size; }
          .annika-alarm { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 4px 24px; align-items: start; }
          .annika-alarm .wide { grid-column: 1 / -1; }
          .annika-alarm h3.sec { font-size: 18px; font-weight: 400; margin: 16px 0 8px; color: var(--primary-text-color); }
          .annika-alarm .side h3.sec:first-child { margin-top: 0; }
          .annika-alarm .arming th, .annika-alarm .arming td { width: 33%; }
          .annika-alarm .panel { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 12px);
            padding: 12px 16px; box-sizing: border-box; }
          .annika-alarm .panel.table { padding: 4px 8px; overflow-x: auto; }
          .annika-alarm .muted, .annika-alarm .sub { color: var(--secondary-text-color); font-size: 13px; }
          .annika-alarm input[type=number], .annika-alarm input[type=time], .annika-alarm select {
            background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); color: var(--primary-text-color);
            border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 8px; font: inherit; font-size: 14px; color-scheme: dark light; }
          .annika-alarm input[type=number] { width: 64px; }

          .annika-ak { padding: 16px; display: flex; flex-direction: column; align-items: center; gap: 14px; }
          .annika-ak .top { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
          .annika-ak .name { font-weight: 500; font-size: 18px; }
          .annika-ak .chip { display: inline-flex; gap: 8px; align-items: center; padding: 4px 12px; border-radius: 999px; font-size: 13px;
            background: color-mix(in srgb, var(--disabled-color) 25%, transparent); color: var(--primary-text-color); }
          .annika-ak .chip.armed, .annika-ak .chip.arming { background: color-mix(in srgb, var(--primary-color) 22%, transparent); }
          .annika-ak .chip.pending, .annika-ak .chip.triggered { background: color-mix(in srgb, var(--error-color, #db4437) 28%, transparent); }
          .annika-ak .modes { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; width: 100%; min-height: 36px; }
          .annika-ak .mode { border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
            border-radius: 999px; padding: 8px 14px; font: inherit; font-size: 14px; cursor: pointer; }
          .annika-ak .mode.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
          .annika-ak .mode.disarm { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); cursor: default; }
          .annika-ak .prompt { color: var(--secondary-text-color); font-size: 14px; text-align: center; }
          .annika-ak .dots { display: flex; gap: 10px; height: 14px; align-items: center; }
          .annika-ak .dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--disabled-color); box-sizing: border-box; }
          .annika-ak .dot.full { background: var(--primary-color); border-color: var(--primary-color); }
          .annika-ak .pad { display: grid; grid-template-columns: repeat(3, 64px); gap: 12px; }
          .annika-ak .key { width: 64px; height: 64px; border-radius: 50%; border: 0; cursor: pointer; font: inherit; font-size: 24px;
            background: var(--primary-color); color: var(--text-primary-color, #fff); }
          .annika-ak .key.back { background: transparent; color: var(--primary-text-color); border: 1px solid var(--divider-color); font-size: 20px; }
          .annika-ak .key.ok { background: transparent; color: var(--primary-color); border: 2px solid var(--primary-color); font-size: 26px; }
          .annika-ak .key:active { filter: brightness(.85); }
          .annika-ak .key:disabled { opacity: .4; cursor: default; }
          .annika-ak .msg { font-size: 13px; min-height: 18px; text-align: center; }
          .annika-ak .msg.error { color: var(--error-color, #db4437); }
          .annika-ak .msg.ok { color: var(--primary-color); }
          .annika-ak .link { background: none; border: 0; color: var(--primary-color); font: inherit; font-size: 14px; cursor: pointer; padding: 4px 8px; }

          .annika-alarm .warning { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; margin-bottom: 0; }
          .annika-alarm .field { display: inline-flex; align-items: center; gap: 8px; }
          .annika-alarm .now { color: var(--primary-color); font-size: 13px; font-style: italic; margin: 10px 0 2px; }
          .annika-alarm table { width: 100%; border-collapse: collapse; }
          .annika-alarm th { text-align: left; font-weight: 400; font-size: 13px; color: var(--secondary-text-color); padding: 10px 8px; }
          .annika-alarm td { padding: 8px; border-top: 1px solid var(--divider-color); vertical-align: middle; }
          .annika-alarm .cell { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
          .annika-alarm .test { text-align: center; width: 64px; }
          .annika-alarm .play { width: 36px; height: 36px; border-radius: 50%; border: 0; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
            background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color); }
          .annika-alarm .play:active { filter: brightness(.8); }
          .annika-alarm .play.running { background: color-mix(in srgb, var(--warning-color, #f5b335) 25%, transparent); color: var(--warning-color, #f5b335); }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}

          .annika-alarm .zones tr.zone td { border-top: 1px solid var(--divider-color); padding-top: 12px; }
          .annika-alarm .zones tr.sensor td { border-top: 1px solid color-mix(in srgb, var(--divider-color) 50%, transparent); }
          .annika-alarm .zones tr.sensor td.name { padding-left: 28px; }
          .annika-alarm .sname { display: flex; align-items: center; gap: 10px; }
          .annika-alarm .sicon { --mdc-icon-size: 20px; flex: none; color: var(--disabled-color); transition: color .2s; }
          .annika-alarm .sicon.on { color: var(--primary-color); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--primary-color) 70%, transparent)); }
          .annika-alarm .zones td.name .sub { margin-left: 6px; }
          .annika-alarm .zones tr.sensor td.name .sub { margin-left: 0; }
          .annika-alarm .own { color: var(--primary-color); font-style: italic; margin-left: 8px; }
          .annika-alarm select.rule { min-width: 112px; }
          .annika-alarm select.rule.off { color: var(--secondary-text-color); }
          .annika-alarm select.rule.warning { color: var(--warning-color, #f5b335); border-color: color-mix(in srgb, var(--warning-color, #f5b335) 45%, transparent);
            background: color-mix(in srgb, var(--warning-color, #f5b335) 12%, transparent); }
          .annika-alarm select.rule.trigger { color: var(--error-color, #ff6b6b); border-color: color-mix(in srgb, var(--error-color, #ff6b6b) 45%, transparent);
            background: color-mix(in srgb, var(--error-color, #ff6b6b) 12%, transparent); }
          .annika-alarm select.rule.inherit { opacity: .5; border-style: dashed; }

          .annika-alarm .decisions { max-height: 340px; overflow-y: auto; }
          .annika-alarm .decision { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--divider-color); }
          .annika-alarm .decision:last-child { border-bottom: 0; }
          .annika-alarm .decision .text { flex: 1; }
          .annika-alarm .decision .time { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; font-size: 13px; }
          .annika-alarm .level { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--disabled-color); }
          .annika-alarm .level.warning { background: var(--warning-color, #f5b335); }
          .annika-alarm .level.trigger { background: var(--error-color, #ff6b6b); }
          .annika-alarm .level.info { background: var(--primary-color); }

          .annika-alarm .auto { display: flex; flex-direction: column; gap: 10px; font-size: 14px; }
          .annika-alarm .auto-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
          .annika-alarm .auto-row.sub { padding-left: 30px; color: var(--secondary-text-color); }
          .annika-alarm .auto-row .quiet { margin-left: 12px; }
          .annika-alarm .auto-row.waiting { color: var(--primary-color); }

          @container (max-width: 800px) {
            .annika-alarm { grid-template-columns: minmax(0, 1fr); }
            .annika-alarm .keypad { max-width: 400px; justify-self: center; width: 100%; }
            .annika-alarm .panel.table { padding: 4px 4px; }
            .annika-alarm table { table-layout: fixed; }
            .annika-alarm td, .annika-alarm th { padding: 8px 3px; }
            .annika-alarm select.rule { min-width: 0; width: 100%; padding: 6px 2px; font-size: 12px; }
            .annika-alarm .zones th:first-child, .annika-alarm .zones td.name { width: 31%; }
            .annika-alarm .zones tr.sensor td.name { padding-left: 8px; }
            .annika-alarm .sname { gap: 6px; }
            .annika-alarm .zones td.name .sub { display: block; margin-left: 0; }
            .annika-alarm .arming th, .annika-alarm .arming td { width: auto; }
            .annika-alarm .fires th:first-child, .annika-alarm .fires td.device { width: 27%; }
            .annika-alarm .fires th.test, .annika-alarm .fires td.test { width: 44px; }
            .annika-alarm .fires td.device .sub { display: none; }
            .annika-alarm .fires .cell { gap: 4px; flex-wrap: wrap; white-space: normal; }
            .annika-alarm .fires .cell .muted { display: none; }
            .annika-alarm .fires input[type=number] { width: 44px; padding: 6px 4px; }
            .annika-alarm .fires select { padding: 6px 2px; font-size: 12px; }
            .annika-alarm .play { width: 32px; height: 32px; }
          }
        </style>
        <div class="annika-alarm">
          ${this._keypadHtml(stateObj, t)}
          ${side}
          ${zones}
          ${this._autoHtml(stateObj, t)}
          ${activity}
        </div>
      `
      this._bind()
    }

    _bind() {
      const on = (selector, event, handler) =>
        this.querySelectorAll(selector).forEach((el) => el.addEventListener(event, () => handler(el)))
      const hass = this._hass

      on('[data-key]', 'click', (el) => this._press(el.dataset.key))
      on('[data-mode].mode', 'click', (el) => this._chooseMode(el.dataset.mode))
      on('[data-change]', 'click', () => this._startChange())
      on('[data-cancel]', 'click', () => this._cancelChange())

      on('[data-warning]', 'change', (el) => {
        if (el.value !== '') this._service('set_warning', { [el.dataset.warning]: Number(el.value) })
      })
      on('[data-out-warning]', 'change', (el) => this._service('set_output', { output: el.dataset.outWarning, warning_enabled: el.checked }))
      on('[data-out-trigger]', 'change', (el) => this._service('set_output', { output: el.dataset.outTrigger, trigger_enabled: el.checked }))
      const duration = (id) => {
        const value = Number(this.querySelector(`[data-duration="${id}"]`).value)
        const unit = Number(this.querySelector(`[data-unit="${id}"]`).value)
        if (value > 0) this._service('set_output', { output: id, warning_seconds: Math.round(value * unit) })
      }
      on('[data-duration]', 'change', (el) => duration(el.dataset.duration))
      on('[data-unit]', 'change', (el) => duration(el.dataset.unit))
      on('[data-notify]', 'change', (el) => this._service('set_notification', { [el.dataset.notify]: el.checked }))
      on('[data-timing]', 'change', (el) => {
        if (el.value !== '') this._service('set_timing', { mode: el.dataset.timing, [el.dataset.key]: Number(el.value) })
      })
      on('[data-test]', 'click', (el) => this._service('test_output', { output: el.dataset.test }))

      on('select[data-zone]', 'change', (el) =>
        this._service('set_rule', { target: 'zone', id: el.dataset.zone, mode: el.dataset.mode, rule: el.value }))
      on('select[data-sensor]', 'change', (el) =>
        this._service('set_rule', { target: 'sensor', id: el.dataset.sensor, mode: el.dataset.mode, rule: el.value || null }))

      on('[data-select]', 'change', (el) =>
        hass.callService('select', 'select_option', { entity_id: el.dataset.select, option: el.value }))
      on('[data-switch]', 'change', (el) =>
        hass.callService('switch', el.checked ? 'turn_on' : 'turn_off', { entity_id: el.dataset.switch }))
      on('[data-time]', 'change', (el) => {
        if (el.value) hass.callService('time', 'set_value', { entity_id: el.dataset.time, time: `${el.value}:00` })
      })
      on('[data-number]', 'change', (el) => {
        if (el.value !== '') hass.callService('number', 'set_value', { entity_id: el.dataset.number, value: Number(el.value) })
      })
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaAlarmCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Alarm',
    description: 'Keypad, warnings, outputs, zone and sensor rules, decisions and automatic arming of the Annika alarm.',
  })
})()
