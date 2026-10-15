// Annika cameras card: what each camera does when it detects something, when
// that counts, and the clips it has recorded (see cameras.py).
//
// Four parts: the cameras live, the recording settings (when detections count,
// how long a clip is, how long clips are kept), what each camera does for each
// kind of detection (nothing, record, or record and notify), and the clips.
// A notification is an option of the recording: there is no way to be told
// about something that was not recorded.
//
// Usage in a dashboard view:
//   type: custom:annika-cameras-card
//   entity: sensor.annika_cameras
//   name: Cameras               # optional
//   language: es                # optional; by default the Home Assistant language
;(() => {
  const CARD = 'annika-cameras-card'
  const SERVICE_DOMAIN = 'annika'

  const TEXTS = {
    en: {
      missing: 'Entity not found: {entity}',
      cameras: 'Cameras',
      recording: 'Recording',
      when: 'When',
      always: 'Always',
      armed: 'Alarm armed',
      time: 'Time range',
      from: 'from',
      to: 'to',
      mode_away: 'Away',
      mode_night: 'Night',
      mode_vacation: 'Vacation',
      before: 'Seconds before',
      after: 'Seconds after',
      cooldown: 'Pause between clips (s)',
      keep_days: 'Keep clips (days)',
      picture: 'A picture is taken with every clip.',
      does: 'What each camera does',
      own_rule: 'overwritten',
      person: 'Person',
      vehicle: 'Vehicle',
      animal: 'Animal',
      motion: 'Motion',
      off: 'Off',
      record: 'Record',
      record_notify: 'Record + notify',
      no_notification: 'Notifications need a notify_view in the configuration.',
      clips: 'Clips',
      no_clips: 'No clips yet',
      delete: 'Delete',
      close: 'Close',
      loading: 'Loading…',
      cannot_play: 'This clip cannot be played',
      notified: 'Notified',
      just_now: 'just now',
    },
    es: {
      missing: 'No se encontró la entidad: {entity}',
      cameras: 'Cámaras',
      recording: 'Grabación',
      when: 'Cuándo',
      always: 'Siempre',
      armed: 'Alarma armada',
      time: 'Rango horario',
      from: 'desde',
      to: 'hasta',
      mode_away: 'Afuera',
      mode_night: 'Noche',
      mode_vacation: 'Vacaciones',
      before: 'Segundos antes',
      after: 'Segundos después',
      cooldown: 'Pausa entre clips (s)',
      keep_days: 'Guardar clips (días)',
      picture: 'Con cada clip se saca una foto.',
      does: 'Qué hace cada cámara',
      own_rule: 'sobrescrita',
      person: 'Persona',
      vehicle: 'Vehículo',
      animal: 'Animal',
      motion: 'Movimiento',
      off: 'Apagado',
      record: 'Grabar',
      record_notify: 'Grabar + avisar',
      no_notification: 'Las notificaciones necesitan notify_view en la configuración.',
      clips: 'Clips',
      no_clips: 'Todavía no hay clips',
      delete: 'Borrar',
      close: 'Cerrar',
      loading: 'Cargando…',
      cannot_play: 'No se puede reproducir este clip',
      notified: 'Avisado',
      just_now: 'recién',
    },
  }

  const KINDS = ['person', 'vehicle', 'animal', 'motion']
  const ACTIONS = ['off', 'record', 'record_notify']
  const MODES = ['away', 'night', 'vacation']
  const ICONS = { person: 'mdi:account', vehicle: 'mdi:car', animal: 'mdi:paw', motion: 'mdi:motion-sensor' }

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')

  class AnnikaCamerasCard extends HTMLElement {
    setConfig(config) {
      if (!config.entity) throw new Error(`${CARD}: "entity" is required`)
      this._config = config
      this._structure = ''
      this._live = {}
      this._playing = null
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      this._render()
      this._updateSensors()
      Object.values(this._live).forEach((el) => (el.hass = hass))
    }

    getCardSize() {
      return 10
    }

    // Full width: a narrow column would switch the card to its mobile layout.
    getGridOptions() {
      return { columns: 'full' }
    }

    getLayoutOptions() {
      return { grid_columns: 'full' }
    }

    get _texts() {
      const lang = (window.Annika && window.Annika.language)
        ? window.Annika.language(this._hass, this._config)
        : (this._config.language || (this._hass && this._hass.language) || 'en')
      const base = String(lang).toLowerCase().split('-')[0]
      return { ...TEXTS.en, ...(TEXTS[base] || {}) }
    }

    get _stateObj() {
      return this._hass && this._hass.states[this._config.entity]
    }

    // The alarm modes that exist and are enabled (null when no alarm panel is found):
    // the only ones worth offering as a recording condition.
    get _alarmModes() {
      const states = (this._hass && this._hass.states) || {}
      const id = Object.keys(states).find(
        (key) => key.startsWith('alarm_control_panel.') && states[key].attributes && states[key].attributes.modes
      )
      if (!id) return null
      const listed = states[id].attributes.modes
      return MODES.filter((mode) => listed[mode] && listed[mode].enabled !== false)
    }

    _service(service, data) {
      return this._hass.callService(SERVICE_DOMAIN, service, { entity_id: this._config.entity, ...data })
    }

    _sensorOn(entityId) {
      const state = this._hass && this._hass.states[entityId]
      return !!state && state.state === 'on'
    }

    _updateSensors() {
      this.querySelectorAll('[data-sensor-state]').forEach((el) => {
        el.classList.toggle('on', this._sensorOn(el.dataset.sensorState))
      })
    }

    // --- pieces -----------------------------------------------------------

    _icon(name) {
      return `<ha-icon icon="${name}"></ha-icon>`
    }

    _camerasHtml(config, t) {
      const tiles = config.cameras.map((camera) => {
        const chips = KINDS.filter((kind) => camera.sensors[kind]).map((kind) =>
          `<span class="chip${this._sensorOn(camera.sensors[kind]) ? ' on' : ''}" data-sensor-state="${escapeHtml(camera.sensors[kind])}" title="${escapeHtml(t[kind])}">${this._icon(ICONS[kind])}</span>`
        ).join('')
        return `<ha-card class="tile">
          <div class="live" data-live="${escapeHtml(camera.id)}"><span class="placeholder">${escapeHtml(camera.name)}</span></div>
          <div class="caption"><span>${escapeHtml(camera.name)}</span><span class="chips">${chips}</span></div>
        </ha-card>`
      }).join('')
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.cameras)}">${escapeHtml(t.cameras)}</div><div class="tiles">${tiles}</div></div>`
    }

    _recordingHtml(config, t) {
      const { when, recording } = config
      const check = (attrs, on) => `<input type="checkbox" class="annika-check" ${attrs}${on ? ' checked' : ''}>`
      const shown = this._alarmModes || MODES
      const modes = MODES.filter((mode) => shown.includes(mode)).map((mode) =>
        `<label class="field">${check(`data-mode="${mode}"${when.armed ? '' : ' disabled'}`, when.armed_modes.includes(mode))}<span>${escapeHtml(t[`mode_${mode}`])}</span></label>`
      ).join('')
      const number = (key, min, max) =>
        `<label class="setting"><span>${escapeHtml(t[key])}</span><input type="number" data-rec="${key}" min="${min}" max="${max}" value="${escapeHtml(recording[key])}"></label>`
      const alwaysOff = when.always ? ' disabled' : ''
      return `<div class="wide">
        <div class="sec" data-heading="${escapeHtml(t.recording)}">${escapeHtml(t.recording)}</div>
        <ha-card class="panel recording">
          <div class="col">
          <div class="muted">${escapeHtml(t.when)}</div>
          <div class="when">
            <label class="field">${check('data-when="always"', when.always)}<span>${escapeHtml(t.always)}</span></label>
            <div class="row${when.always ? ' dim' : ''}">
              <label class="field">${check(`data-when="armed"${alwaysOff}`, when.armed)}<span>${escapeHtml(t.armed)}</span></label>
              <div class="modes">${modes}</div>
            </div>
            <div class="row${when.always ? ' dim' : ''}">
              <label class="field">${check(`data-when="time"${alwaysOff}`, when.time)}<span>${escapeHtml(t.time)}</span></label>
              <span class="range">
                <span class="muted">${escapeHtml(t.from)}</span>
                <input type="time" data-clock="from" value="${escapeHtml(when.from)}"${when.time && !when.always ? '' : ' disabled'}>
                <span class="muted">${escapeHtml(t.to)}</span>
                <input type="time" data-clock="to" value="${escapeHtml(when.to)}"${when.time && !when.always ? '' : ' disabled'}>
              </span>
            </div>
          </div>
          </div>
          <div class="col nums">
          <div class="numbers">
            ${number('before', 0, 60)}${number('after', 1, 300)}${number('cooldown', 0, 3600)}${number('keep_days', 1, 365)}
          </div>
          </div>
        </ha-card>
      </div>`
    }

    _doesHtml(config, t) {
      const head = KINDS.map((kind) => `<th>${escapeHtml(t[kind])}</th>`).join('')
      const groups = config.groups || []
      const groupOf = (id) => groups.find((group) => group.id === id)
      const option = (value, action, selected, label) =>
        `<option value="${value}"${selected ? ' selected' : ''}>${escapeHtml(label || t[action])}</option>`
      const groupRow = (group) => {
        const cells = KINDS.map((kind) => {
          if (!group.kinds.includes(kind)) return '<td class="none" data-label="">—</td>'
          const action = group.rules[kind] || 'off'
          const options = ACTIONS.map((a) => option(a, a, a === action)).join('')
          return `<td data-label="${escapeHtml(t[kind])}"><select class="rule ${action}" data-group="${escapeHtml(group.id)}" data-kind="${kind}">${options}</select></td>`
        }).join('')
        return `<tr class="group"><td class="name"><b>${escapeHtml(group.name)}</b></td>${cells}</tr>`
      }
      const cameraRow = (camera) => {
        const group = groupOf(camera.group)
        const own = group && KINDS.some((kind) => camera.sensors[kind] && camera.rules[kind])
        const cells = KINDS.map((kind) => {
          if (!camera.sensors[kind]) return '<td class="none" data-label="">—</td>'
          const selected = camera.rules[kind] || null
          const effective = selected || (group ? group.rules[kind] : null) || 'off'
          const inherit = group ? option('', effective, selected === null, t[effective]) : ''
          const options = inherit + ACTIONS.map((a) => option(a, a, a === selected)).join('')
          return `<td data-label="${escapeHtml(t[kind])}"><select class="rule ${effective}${group && selected === null ? ' inherit' : ''}" data-camera="${escapeHtml(camera.id)}" data-kind="${kind}">${options}</select></td>`
        }).join('')
        const mark = own ? ` <span class="own">${escapeHtml(t.own_rule)}</span>` : ''
        return `<tr class="${group ? 'member' : ''}"><td class="name">${escapeHtml(camera.name)}${mark}</td>${cells}</tr>`
      }
      const rows = []
      for (const group of groups) {
        rows.push(groupRow(group))
        config.cameras.filter((camera) => camera.group === group.id).forEach((camera) => rows.push(cameraRow(camera)))
      }
      config.cameras.filter((camera) => !groupOf(camera.group)).forEach((camera) => rows.push(cameraRow(camera)))
      const hint = config.notification ? '' : `<div class="muted note">${escapeHtml(t.no_notification)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.does)}">${escapeHtml(t.does)}</div>
        <ha-card class="panel table"><table class="does"><thead><tr><th></th>${head}</tr></thead><tbody>${rows.join('')}</tbody></table></ha-card>${hint}</div>`
    }

    _ago(iso) {
      const seconds = Math.round((new Date(iso) - Date.now()) / 1000)
      if (Math.abs(seconds) < 60) return this._texts.just_now
      const lang = String((this._hass && this._hass.language) || 'en')
      const format = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
      for (const [unit, size] of [['day', 86400], ['hour', 3600], ['minute', 60]]) {
        if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit)
      }
      return ''
    }

    _clipsHtml(attrs, t) {
      const clips = attrs.clips || []
      const body = clips.length
        ? clips.map((clip) => {
            let picture = ''
            if (clip.image && attrs.image_base) {
              const path = `${attrs.image_base}/${clip.image}`
              // /local is public; /media/local needs a signed URL, filled in after the render.
              picture = path.startsWith('/media/')
                ? `<img data-signed="${escapeHtml(path)}" alt="" loading="lazy">`
                : `<img src="${escapeHtml(path)}" alt="" loading="lazy">`
            }
            const bell = clip.notified ? `<span class="bell" title="${escapeHtml(t.notified)}">${this._icon('mdi:bell')}</span>` : ''
            return `<button class="clip" data-clip="${escapeHtml(clip.id)}">
              <span class="thumb">${picture}<span class="play">${this._icon('mdi:play')}</span>${bell}</span>
              <span class="meta"><span class="what">${this._icon(ICONS[clip.type] || 'mdi:video')}${escapeHtml(clip.camera)}</span>
              <span class="muted">${escapeHtml(t[clip.type] || clip.type)} · ${escapeHtml(this._ago(clip.time))}</span></span>
            </button>`
          }).join('')
        : `<div class="muted empty">${escapeHtml(t.no_clips)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.clips)}">${escapeHtml(t.clips)}</div><div class="carousel">${body}</div></div>`
    }

    _playerHtml(t) {
      const playing = this._playing
      if (!playing) return ''
      const media = playing.url
        ? `<video src="${escapeHtml(playing.url)}" controls autoplay playsinline></video>`
        : `<div class="status">${escapeHtml(playing.error ? t.cannot_play : t.loading)}</div>`
      return `<div class="player" data-close-bg>
        <div class="box">
          ${media}
          <div class="bar"><span>${escapeHtml(playing.clip.camera)} · ${escapeHtml(t[playing.clip.type] || playing.clip.type)}</span>
          <span><button class="link danger" data-delete="${escapeHtml(playing.clip.id)}">${escapeHtml(t.delete)}</button>
          <button class="link" data-close>${escapeHtml(t.close)}</button></span></div>
        </div></div>`
    }

    // --- rendering --------------------------------------------------------

    _render(force) {
      if (!this._config) return
      const stateObj = this._stateObj
      const t = this._texts
      if (!stateObj) {
        this.innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(fill(t.missing, { entity: this._config.entity }))}</div></ha-card>`
        this._structure = ''
        return
      }
      const attrs = stateObj.attributes
      const config = attrs.config
      if (!config) return
      const key = JSON.stringify([config, this._alarmModes, attrs.clips, attrs.image_base, t.cameras, this._playing && [this._playing.url, this._playing.error]])
      if (!force && key === this._structure) return
      this._structure = key

      // Keep the height while the content is rebuilt (the titles arrive a moment later):
      // on a phone a shorter page would scroll itself back to the top.
      const keep = this.offsetHeight
      if (keep) this.style.minHeight = `${keep}px`
      this.innerHTML = `
        <style>
          annika-cameras-card { display: block; container-type: inline-size; }
          .annika-cams { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0; }
          .annika-cams .wide { grid-column: 1 / -1; margin-top: 16px; display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
          .annika-cams .sec { font-size: 16px; font-weight: 500; padding: 4px 4px 0; color: var(--primary-text-color); }
          .annika-cams .annika-heading { display: block; }
          .annika-cams ha-card.panel { display: block; padding: 12px 16px; box-sizing: border-box; }
          .annika-cams ha-card.panel.table { padding: 4px 8px; overflow-x: auto; }
          .annika-cams .muted { color: var(--secondary-text-color); font-size: 13px; }
          .annika-cams .note { margin-top: 10px; }
          .annika-cams input[type=number], .annika-cams input[type=time], .annika-cams select {
            background: var(--secondary-background-color, transparent); color: var(--primary-text-color);
            border: 1px solid var(--divider-color); border-radius: 6px; padding: 4px 6px; font: inherit; font-size: 14px; color-scheme: dark light; }
          .annika-cams input[type=number] { width: 64px; }
          .annika-cams input:disabled { opacity: .45; }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}

          .annika-cams .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
          .annika-cams ha-card.tile { display: block; overflow: hidden; }
          .annika-cams .live { aspect-ratio: 16 / 9; background: #000; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); overflow: hidden; }
          .annika-cams .live > * { width: 100%; }
          .annika-cams .caption { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; gap: 8px; }
          .annika-cams .chips { display: inline-flex; gap: 6px; }
          .annika-cams .chip { --mdc-icon-size: 18px; display: inline-flex; color: var(--disabled-color); transition: color .2s; }
          .annika-cams .chip.on { color: var(--primary-color); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--primary-color) 70%, transparent)); }

          .annika-cams ha-card.recording { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 16px 32px; }
          .annika-cams .recording .when { display: flex; flex-direction: column; gap: 10px; margin: 6px 0 0; }
          .annika-cams .recording .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
          .annika-cams .recording .col { flex: 1 1 320px; }
          .annika-cams .recording .col.nums { border-left: 1px solid var(--divider-color); padding-left: 32px; }
          .annika-cams .recording .row.dim { opacity: .5; }
          .annika-cams .field { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; }
          .annika-cams .modes { display: flex; flex-wrap: wrap; gap: 6px 16px; }
          .annika-cams .range { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
          .annika-cams .range input[type=time] { width: 112px; padding: 6px 6px; }
          .annika-cams .setting { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 14px; }
          .annika-cams .numbers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin-top: 6px; }

          .annika-cams table { width: 100%; border-collapse: collapse; }
          .annika-cams th { text-align: left; font-weight: 400; font-size: 13px; color: var(--secondary-text-color); padding: 10px 8px; }
          .annika-cams td { padding: 8px; border-top: 1px solid var(--divider-color); vertical-align: middle; }
          .annika-cams td.none { color: var(--disabled-color); }
          .annika-cams select.rule { width: 100%; min-width: 120px; }
          .annika-cams select.rule.inherit { border-style: dashed; opacity: .75; }
          .annika-cams .does tr.member td.name { padding-left: 20px; }
          .annika-cams .does .own { color: var(--primary-color); font-size: 12px; margin-left: 6px; }
          .annika-cams select.rule.off { color: var(--secondary-text-color); }
          .annika-cams select.rule.record { color: var(--primary-color); border-color: color-mix(in srgb, var(--primary-color) 45%, transparent);
            background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
          .annika-cams select.rule.record_notify { color: var(--warning-color, #f5b335); border-color: color-mix(in srgb, var(--warning-color, #f5b335) 45%, transparent);
            background: color-mix(in srgb, var(--warning-color, #f5b335) 12%, transparent); }

          .annika-cams .carousel { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; scroll-snap-type: x proximity; }
          .annika-cams .clip { flex: none; width: 220px; background: var(--ha-card-background, var(--card-background-color)); border: 0; border-radius: var(--ha-card-border-radius, 0); padding: 0;
            text-align: left; cursor: pointer; color: inherit; font: inherit; overflow: hidden; scroll-snap-align: start; }
          .annika-cams .thumb { position: relative; display: block; aspect-ratio: 16 / 9; background: #000; }
          .annika-cams .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
          .annika-cams .thumb .play { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; --mdc-icon-size: 36px;
            background: linear-gradient(transparent 55%, rgba(0,0,0,.45)); }
          .annika-cams .thumb .bell { position: absolute; top: 6px; right: 6px; --mdc-icon-size: 16px; color: var(--warning-color, #f5b335);
            background: rgba(0,0,0,.55); border-radius: 999px; padding: 3px; display: inline-flex; }
          .annika-cams .meta { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px 10px; }
          .annika-cams .what { display: flex; align-items: center; gap: 6px; font-size: 14px; --mdc-icon-size: 16px; }
          .annika-cams .empty { padding: 12px 0; }

          .annika-cams .player { position: fixed; inset: 0; z-index: 9; background: rgba(0,0,0,.7); display: flex; align-items: center; justify-content: center; padding: 16px; }
          .annika-cams .player .box { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 0); overflow: hidden; width: min(900px, 100%); }
          .annika-cams .player video { width: 100%; display: block; background: #000; max-height: 70vh; }
          .annika-cams .player .status { aspect-ratio: 16 / 9; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
          .annika-cams .player .bar { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; font-size: 14px; }
          .annika-cams .link { background: none; border: 0; color: var(--primary-color); font: inherit; font-size: 14px; cursor: pointer; padding: 4px 8px; }
          .annika-cams .link.danger { color: var(--error-color, #db4437); }

          @container (max-width: 800px) {
            .annika-cams { grid-template-columns: minmax(0, 1fr); }
            .annika-cams .tiles { grid-template-columns: minmax(0, 1fr); }
            .annika-cams ha-card.panel.table { padding: 4px 4px; }
            .annika-cams .recording .col.nums { border-left: 0; padding-left: 0; border-top: 1px solid var(--divider-color); padding-top: 12px; }
            .annika-cams .numbers { grid-template-columns: 1fr; }
            .annika-cams .does thead { display: none; }
            .annika-cams .does, .annika-cams .does tbody { display: block; }
            .annika-cams .does tr { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; padding: 10px 8px; border-top: 1px solid var(--divider-color); }
            .annika-cams .does tr:first-child { border-top: 0; }
            .annika-cams .does td { border: 0; padding: 0; }
            .annika-cams .does td.name { grid-column: 1 / -1; font-weight: 500; }
            .annika-cams .does td.none { display: none; }
            .annika-cams .does td[data-label]::before { content: attr(data-label); display: block; font-size: 12px; color: var(--secondary-text-color); margin-bottom: 2px; }
            .annika-cams select.rule { min-width: 0; }
            .annika-cams .clip { width: 180px; }
          }
        </style>
        <div class="annika-cams">
          ${this._camerasHtml(config, t)}
          ${this._recordingHtml(config, t)}
          ${this._doesHtml(config, t)}
          ${this._clipsHtml(attrs, t)}
        </div>
        ${this._playerHtml(t)}
      `
      this._bind(config, attrs)
      this._signImages()
      this._mountLive(config)
      this._headings().then(() => requestAnimationFrame(() => { this.style.minHeight = '' }))
    }

    // Section titles are Home Assistant's own heading card, like the other
    // Annika cards; the plain text stays until it is ready.
    async _headings() {
      if (!window.loadCardHelpers || !window.Annika) return
      try {
        const helpers = await window.loadCardHelpers()
        for (const host of this.querySelectorAll('[data-heading]')) {
          const card = await helpers.createCardElement(window.Annika.headingConfig(host.dataset.heading, { style: 'title' }))
          card.hass = this._hass
          card.classList.add('annika-heading')
          if (host.isConnected) host.replaceChildren(card)
        }
      } catch (err) {
        // The plain title stays.
      }
    }

    // The live tiles are Home Assistant's own cards, built once and moved back
    // into place after every render so the stream does not restart.
    async _mountLive(config) {
      for (const camera of config.cameras) {
        const holder = this.querySelector(`[data-live="${CSS.escape(camera.id)}"]`)
        if (!holder) continue
        if (this._live[camera.id]) {
          holder.replaceChildren(this._live[camera.id])
          continue
        }
        if (!window.loadCardHelpers) continue
        try {
          const helpers = await window.loadCardHelpers()
          if (this._live[camera.id]) continue
          const el = await helpers.createCardElement({
            type: 'picture-entity', entity: camera.entity, camera_view: 'live', show_name: false, show_state: false,
          })
          el.hass = this._hass
          this._live[camera.id] = el
          const target = this.querySelector(`[data-live="${CSS.escape(camera.id)}"]`)
          if (target) target.replaceChildren(el)
        } catch (err) {
          // The placeholder with the camera's name stays.
        }
      }
    }

    // Pictures under /media are behind Home Assistant's login: ask for a signed
    // link per picture, once, and keep it for most of its hour.
    _signImages() {
      const cache = (this._signed ||= new Map())
      for (const img of this.querySelectorAll('img[data-signed]')) {
        const path = img.dataset.signed
        const hit = cache.get(path)
        if (hit && hit.failed && hit.until > Date.now()) continue
        if (hit && hit.url && hit.until > Date.now()) {
          img.src = hit.url
          continue
        }
        if (hit && hit.pending) {
          hit.pending.then(() => this._signImages())
          continue
        }
        const pending = this._hass
          .callWS({ type: 'auth/sign_path', path, expires: 3600 })
          .then((result) => {
            const url = this._hass.hassUrl ? this._hass.hassUrl(result.path) : result.path
            cache.set(path, { url, until: Date.now() + 50 * 60 * 1000 })
          })
          .catch(() => cache.set(path, { failed: true, until: Date.now() + 60 * 1000 }))
        cache.set(path, { pending, until: 0 })
        pending.then(() => this._signImages())
      }
    }

    async _play(clip, attrs) {
      this._playing = { clip, url: null, error: false }
      this._render(true)
      try {
        if (!attrs.media_base) throw new Error('no media folder')
        const result = await this._hass.callWS({
          type: 'media_source/resolve_media',
          media_content_id: `${attrs.media_base}/${clip.video}`,
          expires: 3600,
        })
        const url = this._hass.hassUrl ? this._hass.hassUrl(result.url) : result.url
        if (this._playing && this._playing.clip.id === clip.id) this._playing = { clip, url, error: false }
      } catch (err) {
        if (this._playing && this._playing.clip.id === clip.id) this._playing = { clip, url: null, error: true }
      }
      this._render(true)
    }

    _bind(config, attrs) {
      const on = (selector, event, handler) =>
        this.querySelectorAll(selector).forEach((el) => el.addEventListener(event, (e) => handler(el, e)))
      const modes = () =>
        MODES.filter((mode) => {
          const box = this.querySelector(`[data-mode="${mode}"]`)
          // A mode the alarm has switched off has no box: it keeps what it had.
          return box ? box.checked : (this._stateObj.attributes.config.when.armed_modes || []).includes(mode)
        })

      // An empty value gives the detection back to the camera's group.
      on('select[data-camera]', 'change', (el) =>
        this._service('set_camera_rule', { camera: el.dataset.camera, type: el.dataset.kind, action: el.value || null }))
      on('select[data-group]', 'change', (el) =>
        this._service('set_group_rule', { group: el.dataset.group, type: el.dataset.kind, action: el.value }))
      on('[data-when]', 'change', (el) => this._service('set_recording_when', { [el.dataset.when]: el.checked }))
      on('[data-mode]', 'change', () => this._service('set_recording_when', { armed_modes: modes() }))
      on('[data-clock]', 'change', (el) => {
        if (el.value) this._service('set_recording_when', { [el.dataset.clock]: `${el.value}:00` })
      })
      on('[data-rec]', 'change', (el) => {
        if (el.value !== '') this._service('set_recording', { [el.dataset.rec]: Number(el.value) })
      })

      on('[data-clip]', 'click', (el) => {
        const clip = (attrs.clips || []).find((c) => c.id === el.dataset.clip)
        if (clip) this._play(clip, attrs)
      })
      on('[data-close]', 'click', () => {
        this._playing = null
        this._render(true)
      })
      on('[data-close-bg]', 'click', (el, e) => {
        if (e.target === el) {
          this._playing = null
          this._render(true)
        }
      })
      on('[data-delete]', 'click', (el) => {
        this._playing = null
        this._service('delete_clip', { clip_id: el.dataset.delete })
        this._render(true)
      })
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaCamerasCard])
})()
