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
//
// Live view: every camera plays its fluent (low resolution) stream, which is
// what a Raspberry Pi can play for all of them at once. A camera with a clear
// (high resolution) stream has an HD button that switches that camera alone
// to it. Both streams are found from the camera's entity (`camera.x_clear` or
// `camera.x_fluent`, as the Reolink integration names them).
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
      hd: 'HD',
      hd_hint: 'Watch this camera in high definition (uses more of the system)',
      settings: 'Settings',
      back: 'Back',
      no_settings: 'This camera has no settings to show',
      confirm_restart: 'Restart this device?',
      confirm_siren: 'Turn the siren on?',
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
      mode_away: 'Salida',
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
      hd: 'HD',
      hd_hint: 'Ver esta cámara en alta definición (usa más recursos)',
      settings: 'Ajustes',
      back: 'Volver',
      no_settings: 'Esta cámara no tiene ajustes para mostrar',
      confirm_restart: '¿Reiniciar este dispositivo?',
      confirm_siren: '¿Encender la sirena?',
    },
  }

  const KINDS = ['person', 'vehicle', 'animal', 'motion']
  const ACTIONS = ['off', 'record', 'record_notify']
  const MODES = ['away', 'night', 'vacation']
  // What the settings of a camera show, in this order; the rest follows.
  const SETTING_DOMAINS = ['switch', 'light', 'siren', 'select', 'number', 'button', 'update', 'binary_sensor', 'sensor']
  // Entities of the device that are not settings (the streams are the tile).
  const HIDDEN_DOMAINS = ['camera', 'image']
  // The tiles' colour, the one the lights and covers cards use for theirs.
  const SETTINGS_COLOR = 'primary'
  const ICONS = { person: 'mdi:account', vehicle: 'mdi:car', animal: 'mdi:paw', motion: 'mdi:motion-sensor' }

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')

  // A dropdown, drawn like the irrigation card's (see SELECT_CSS in annika-common.js).
  const selectBox = (select) => `<span class="annika-select">${select}</span>`

  class AnnikaCamerasCard extends HTMLElement {
    setConfig(config) {
      if (!config.entity) throw new Error(`${CARD}: "entity" is required`)
      this._config = config
      this._structure = ''
      this._live = {}
      this._liveEntity = {}
      // The cameras the person asked to see in HD: none until they ask.
      this._hd = new Set()
      this._playing = null
      // The camera whose settings are open (replaces the card's content), or null.
      this._settings = null
      this._tiles = {}
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      this._render()
      this._updateSensors()
      if (this._settings) Object.values(this._tiles).forEach((el) => (el.hass = hass))
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

    // The two streams of a camera: fluent (what plays by default) and clear
    // (HD, when the camera has both). Named from the camera's entity, which is
    // either one of them. Keep HA's numeric suffix for cameras of the same
    // model (camera.x_clear_2 pairs with camera.x_fluent_2).
    // A camera that is neither has just its own stream.
    _streams(camera) {
      const match = /^(camera\..+)_(clear|fluent)(_\d+)?$/.exec(camera.entity)
      const states = (this._hass && this._hass.states) || {}
      if (!match) return { fluent: camera.entity, clear: null }
      const suffix = match[3] || ''
      const clear = `${match[1]}_clear${suffix}`
      const fluent = `${match[1]}_fluent${suffix}`
      if (!states[clear] || !states[fluent]) return { fluent: camera.entity, clear: null }
      return { fluent, clear }
    }

    _liveEntityFor(camera) {
      const streams = this._streams(camera)
      return streams.clear && this._hd.has(camera.id) ? streams.clear : streams.fluent
    }

    _camerasHtml(config, t) {
      const tiles = config.cameras.map((camera) => {
        const hd = this._streams(camera).clear
          ? `<button class="hd${this._hd.has(camera.id) ? ' on' : ''}" data-hd="${escapeHtml(camera.id)}" aria-pressed="${this._hd.has(camera.id)}" title="${escapeHtml(t.hd_hint)}">${escapeHtml(t.hd)}</button>`
          : ''
        const gear = `<button class="gear" data-settings="${escapeHtml(camera.id)}" title="${escapeHtml(t.settings)}" aria-label="${escapeHtml(t.settings)}">${this._icon('mdi:cog')}</button>`
        const chips = KINDS.filter((kind) => camera.sensors[kind]).map((kind) =>
          `<span class="chip${this._sensorOn(camera.sensors[kind]) ? ' on' : ''}" data-sensor-state="${escapeHtml(camera.sensors[kind])}" title="${escapeHtml(t[kind])}">${this._icon(ICONS[kind])}</span>`
        ).join('')
        return `<ha-card class="tile">
          <div class="live" data-live="${escapeHtml(camera.id)}"><span class="placeholder">${escapeHtml(camera.name)}</span></div>
          <div class="caption"><span>${escapeHtml(camera.name)}</span><span class="chips">${hd}${chips}${gear}</span></div>
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
          return `<td data-label="${escapeHtml(t[kind])}">${selectBox(`<select class="rule${action === 'off' ? ' off' : ''}" data-group="${escapeHtml(group.id)}" data-kind="${kind}">${options}</select>`)}</td>`
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
          return `<td data-label="${escapeHtml(t[kind])}">${selectBox(`<select class="rule${effective === 'off' ? ' off' : ''}${group && selected === null ? ' inherit' : ''}" data-camera="${escapeHtml(camera.id)}" data-kind="${kind}">${options}</select>`)}</td>`
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

    // --- settings of one camera --------------------------------------------
    //
    // Whatever the camera's device exposes, drawn the way the lights and covers
    // cards draw theirs: Home Assistant's own tile card per entity, with the one
    // feature its kind of entity calls for (a switch or a light needs none: the tile
    // itself is the switch), in a grid. Nothing
    // is grouped or hidden by name (yet); the order is by kind of entity, then
    // by name.

    // Config and diagnostic entities are kept on purpose: for a camera they are
    // most of its settings (sensitivity, volume, floodlight mode...). Only
    // hidden ones go; disabled ones have no state.
    _deviceEntities(camera) {
      const registry = (this._hass && this._hass.entities) || {}
      const states = (this._hass && this._hass.states) || {}
      const device = registry[camera.entity] && registry[camera.entity].device_id
      if (!device) return []
      const rank = (id) => {
        const at = SETTING_DOMAINS.indexOf(id.split('.')[0])
        return at < 0 ? SETTING_DOMAINS.length : at
      }
      return Object.keys(registry)
        .filter((id) => registry[id].device_id === device && !registry[id].hidden && !registry[id].hidden_by && states[id] && !HIDDEN_DOMAINS.includes(id.split('.')[0]))
        .sort((a, b) => rank(a) - rank(b) || this._entityName(a, device).localeCompare(this._entityName(b, device)))
    }

    // The entity's name without the device's name in front of it ("E1 Outdoor SE PoE
    // Record" -> "Record"): inside one camera's settings it only takes room. The
    // device's registered name is tried first; when the entity names do not start
    // with it (or the registry has no names), what all of the device's entity
    // names start with in common.
    _entityName(id, device) {
      const state = this._hass.states[id]
      const name = (state.attributes && state.attributes.friendly_name) || id
      const registered = this._hass.devices && this._hass.devices[device]
      const candidates = [registered && (registered.name_by_user || registered.name), this._commonPrefix(device)]
      for (const prefix of candidates) {
        if (prefix && name.length > prefix.length + 1 && name.startsWith(`${prefix} `)) return name.slice(prefix.length + 1)
      }
      return name
    }

    // The words every entity name of a device starts with (nothing with fewer than two names).
    _commonPrefix(device) {
      const registry = this._hass.entities || {}
      const states = this._hass.states || {}
      const names = Object.keys(registry)
        .filter((id) => registry[id].device_id === device && states[id] && states[id].attributes && states[id].attributes.friendly_name)
        .map((id) => states[id].attributes.friendly_name.split(' '))
      if (names.length < 2) return ''
      const common = []
      for (let at = 0; names.every((words) => words[at] !== undefined && words[at] === names[0][at]); at += 1) common.push(names[0][at])
      return common.join(' ')
    }

    // The tile config for one entity (annika-common's tileConfig, as the other cards use it).
    _settingTile(id) {
      const domain = id.split('.')[0]
      const attrs = (this._hass.states[id] && this._hass.states[id].attributes) || {}
      const t = this._texts
      let features = []
      const options = {}
      // A switch or a light has no feature: tapping its tile turns it on and off.
      if (domain === 'select') {
        features = [{ type: 'select-options' }]
      } else if (domain === 'number') {
        features = [{ type: 'numeric-input', style: attrs.mode === 'box' ? 'buttons' : 'slider' }]
      } else if (domain === 'siren') {
        options.tap_action = { action: 'toggle', confirmation: { text: t.confirm_siren } }
      } else if (domain === 'button' && attrs.device_class === 'restart') {
        options.tap_action = { action: 'toggle', confirmation: { text: t.confirm_restart } }
      }
      const device = this._hass.entities[id] && this._hass.entities[id].device_id
      return window.Annika.tileConfig({ entity: id, name: this._entityName(id, device), color: SETTINGS_COLOR }, { ...options, features })
    }

    _settingsHtml(config, t) {
      const camera = config.cameras.find((c) => c.id === this._settings)
      if (!camera) return ''
      const empty = this._deviceEntities(camera).length === 0
      return `<div class="wide">
        <div class="settings-head">
          <button class="hd back" data-back title="${escapeHtml(t.back)}">${this._icon('mdi:arrow-left')}${escapeHtml(t.back)}</button>
          <div class="sec" data-heading="${escapeHtml(`${camera.name} · ${t.settings}`)}">${escapeHtml(camera.name)} · ${escapeHtml(t.settings)}</div>
        </div>
        <div class="annika-tile-row settings">
          <ha-card class="tile live-tile"><div class="live" data-live="${escapeHtml(camera.id)}"><span class="placeholder">${escapeHtml(camera.name)}</span></div></ha-card>
          <span class="settings-tiles" data-settings-tiles></span>
        </div>
        ${empty ? `<div class="muted empty">${escapeHtml(t.no_settings)}</div>` : ''}
      </div>`
    }

    // The tiles are Home Assistant's own cards, built once per entity and put
    // back into place after every render, like the live views.
    async _mountSettings(config) {
      const camera = config.cameras.find((c) => c.id === this._settings)
      if (!camera || !window.loadCardHelpers) return
      try {
        const helpers = await window.loadCardHelpers()
        const elements = []
        for (const id of this._deviceEntities(camera)) {
          if (!this._tiles[id]) {
            const element = await helpers.createCardElement(this._settingTile(id))
            element.hass = this._hass
            this._tiles[id] = element
          }
          elements.push(this._tiles[id])
        }
        // Went back while these were being built: nothing to put them in.
        const target = this._settings === camera.id && this.querySelector('[data-settings-tiles]')
        if (target) target.replaceChildren(...elements)
      } catch (err) {
        // The camera's own tile stays.
      }
    }

    _openSettings(id) {
      this._settings = id
      this._render(true)
      if (this.scrollIntoView) this.scrollIntoView({ block: 'start' })
    }

    _closeSettings() {
      this._settings = null
      this._render(true)
      if (this.scrollIntoView) this.scrollIntoView({ block: 'start' })
    }

    _ago(iso) {
      const seconds = Math.round((new Date(iso) - Date.now()) / 1000)
      if (Math.abs(seconds) < 60) return this._texts.just_now
      const lang = String((window.Annika && window.Annika.language(this._hass, this._config)) || (this._hass && this._hass.language) || 'en')
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

    // The player is a modal <dialog>: it is drawn in the browser's top layer, so
    // it fills the whole screen whatever Home Assistant's page puts around the
    // card (a fixed box inside the card is placed against the card, not the
    // screen). It lives next to the card's content, not in it, so drawing the
    // card again (a new clip, a state change) does not restart the video.
    _playerHtml(t) {
      const playing = this._playing
      const media = playing.url
        ? `<video src="${escapeHtml(playing.url)}" controls autoplay playsinline></video>`
        : `<div class="status">${escapeHtml(playing.error ? t.cannot_play : t.loading)}</div>`
      return `<div class="top"><span class="title">${escapeHtml(playing.clip.camera)} · ${escapeHtml(t[playing.clip.type] || playing.clip.type)}</span>
        <span><button class="link danger" data-delete="${escapeHtml(playing.clip.id)}">${escapeHtml(t.delete)}</button>
        <button class="link" data-close>${escapeHtml(t.close)}</button></span></div>${media}`
    }

    _syncPlayer() {
      const playing = this._playing
      let dialog = this._dialog
      if (!playing) {
        this._playerKey = null
        if (dialog) {
          if (dialog.open) dialog.close()
          dialog.replaceChildren()
        }
        return
      }
      if (!dialog) {
        dialog = document.createElement('dialog')
        dialog.className = 'annika-player'
        // Escape closes a modal dialog by itself: forget the clip too.
        dialog.addEventListener('close', () => {
          if (this._playing) {
            this._playing = null
            this._syncPlayer()
          }
        })
        dialog.addEventListener('click', (event) => {
          const button = event.target.closest && event.target.closest('[data-close],[data-delete]')
          if (!button) return
          const id = button.dataset.delete
          this._playing = null
          this._syncPlayer()
          if (id) this._service('delete_clip', { clip_id: id })
        })
        this._dialog = dialog
        this.appendChild(dialog)
      }
      const key = JSON.stringify([playing.clip.id, playing.url, playing.error, this._texts.close])
      if (key !== this._playerKey) {
        this._playerKey = key
        dialog.innerHTML = this._playerHtml(this._texts)
      }
      if (!dialog.open) dialog.showModal()
    }

    _bodyElement() {
      if (!this._body) {
        this._body = document.createElement('div')
        this.appendChild(this._body)
      }
      return this._body
    }

    // Which entities the open camera's device has: when they change, the settings are drawn again.
    _deviceKey(config) {
      const camera = config.cameras.find((c) => c.id === this._settings)
      return camera ? this._deviceEntities(camera).join(',') : ''
    }

    // --- rendering --------------------------------------------------------

    _render(force) {
      if (!this._config) return
      const stateObj = this._stateObj
      const t = this._texts
      if (!stateObj) {
        this._bodyElement().innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(fill(t.missing, { entity: this._config.entity }))}</div></ha-card>`
        this._structure = ''
        return
      }
      const attrs = stateObj.attributes
      const config = attrs.config
      if (!config) return
      // A camera that is no longer in the configuration has no settings to show.
      if (this._settings && !config.cameras.some((camera) => camera.id === this._settings)) this._settings = null
      // HD updates its own tile directly; it must not rebuild the other streams.
      const key = JSON.stringify([config, this._alarmModes, attrs.clips, attrs.image_base, t.cameras, this._settings, this._settings && this._deviceKey(config)])
      if (!force && key === this._structure) return
      this._structure = key

      // Keep the height while the content is rebuilt (the titles arrive a moment later):
      // on a phone a shorter page would scroll itself back to the top.
      const keep = this.offsetHeight
      if (keep) this.style.minHeight = `${keep}px`
      this._bodyElement().innerHTML = `
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
          .annika-cams input[type=number], .annika-cams input[type=time] {
            background: var(--secondary-background-color, transparent); color: var(--primary-text-color);
            border: 1px solid var(--divider-color); border-radius: 6px; padding: 4px 6px; font: inherit; font-size: 14px; color-scheme: dark light; }
          .annika-cams input[type=number] { width: 64px; }
          .annika-cams input:disabled { opacity: .45; }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}
          ${(window.Annika && window.Annika.SELECT_CSS) || ''}

          .annika-cams .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
          .annika-cams ha-card.tile { display: block; overflow: hidden; }
          .annika-cams .live { aspect-ratio: 16 / 9; background: #000; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); overflow: hidden; }
          .annika-cams .live > * { width: 100%; }
          .annika-cams .caption { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; gap: 8px; }
          .annika-cams .chips { display: inline-flex; align-items: center; gap: 6px; }
          /* HD: the pill of the alarm's mode buttons, small. */
          .annika-cams .hd { border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); border-radius: 999px;
            padding: 2px 10px; margin-right: 4px; font: inherit; font-size: 12px; cursor: pointer; }
          .annika-cams .hd.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
          .annika-cams .gear { border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; padding: 4px; margin-left: 2px;
            --mdc-icon-size: 20px; display: inline-flex; border-radius: 50%; }
          .annika-cams .gear:hover { color: var(--primary-text-color); }
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
          .annika-cams td > .annika-select { display: block; }
          .annika-cams .annika-select select.rule { min-width: 120px; }
          .annika-cams select.rule.inherit { opacity: .55; }
          .annika-cams .does tr.member td.name { padding-left: 20px; }
          .annika-cams .does .own { color: var(--primary-color); font-size: 12px; margin-left: 6px; }
          .annika-cams select.rule.off { color: var(--secondary-text-color); }

          .annika-cams .settings-head { display: flex; align-items: center; gap: 12px; }
          .annika-cams .settings-head .sec { padding-top: 0; flex: 1; min-width: 0; }
          .annika-cams .hd.back { display: inline-flex; align-items: center; gap: 4px; --mdc-icon-size: 18px; margin-right: 0; padding-left: 8px; }
          /* The lights and covers cards' tile row (the same spacing tokens), with the columns
             fixed instead of fitted: on a desktop three columns of two tiles each, two tiles
             on a tablet, one on a phone. The live view takes the first column (two tiles
             wide) over several rows, and the tiles flow beside it. */
          .annika-cams .annika-tile-row { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
            column-gap: var(--ha-section-column-gap, 8px); row-gap: var(--ha-section-row-gap, 8px); }
          .annika-cams .annika-tile-row > * { min-width: 0; }
          .annika-cams .annika-tile-row .settings-tiles { display: contents; }
          .annika-cams .annika-tile-row > .live-tile { grid-column: span 2; grid-row: span 4; align-self: start; }

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

          dialog.annika-player { position: fixed; inset: 0; margin: 0; padding: 0; border: 0; width: 100vw; height: 100vh; height: 100dvh; max-width: none; max-height: none;
            background: #000; color: #fff; overflow: hidden; box-sizing: border-box; }
          dialog.annika-player[open] { display: flex; flex-direction: column; }
          dialog.annika-player::backdrop { background: #000; }
          .annika-player .top { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 15px;
            padding: max(8px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right)) 8px max(12px, env(safe-area-inset-left)); background: rgba(255,255,255,.08); }
          .annika-player video { flex: 1 1 auto; min-height: 0; width: 100%; display: block; background: #000; object-fit: contain; padding-bottom: env(safe-area-inset-bottom); box-sizing: border-box; }
          .annika-player .status { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.7); }
          .annika-player .link { background: none; border: 0; color: #fff; font: inherit; font-size: 15px; cursor: pointer; padding: 6px 10px; }
          .annika-player .link.danger { color: var(--error-color, #ff6b5e); }
          .annika-cams .link { background: none; border: 0; color: var(--primary-color); font: inherit; font-size: 14px; cursor: pointer; padding: 4px 8px; }
          .annika-cams .link.danger { color: var(--error-color, #db4437); }

          @container (max-width: 1100px) {
            .annika-cams .annika-tile-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .annika-cams .annika-tile-row > .live-tile { grid-column: auto; grid-row: span 3; }
          }
          @container (max-width: 800px) {
            .annika-cams { grid-template-columns: minmax(0, 1fr); }
            .annika-cams .tiles { grid-template-columns: minmax(0, 1fr); }
            .annika-cams .annika-tile-row { grid-template-columns: minmax(0, 1fr); }
            .annika-cams .annika-tile-row > .live-tile { grid-column: auto; grid-row: auto; }
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
            .annika-cams .annika-select select.rule { min-width: 0; }
            .annika-cams .clip { width: 180px; }
          }
        </style>
        <div class="annika-cams">
          ${this._settings
            ? this._settingsHtml(config, t)
            : `${this._camerasHtml(config, t)}${this._recordingHtml(config, t)}${this._doesHtml(config, t)}${this._clipsHtml(attrs, t)}`}
        </div>
      `
      this._bind(config, attrs)
      this._signImages()
      if (this._settings) this._mountSettings(config)
      this._mountLive(this._settings ? { cameras: config.cameras.filter((camera) => camera.id === this._settings) } : config)
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
        // Fluent unless this camera was asked for in HD; a stream already
        // playing for that choice is put back, not restarted.
        const entity = this._liveEntityFor(camera)
        if (this._live[camera.id] && this._liveEntity[camera.id] === entity) {
          holder.replaceChildren(this._live[camera.id])
          continue
        }
        if (!window.loadCardHelpers) continue
        try {
          const helpers = await window.loadCardHelpers()
          if (this._live[camera.id] && this._liveEntity[camera.id] === entity) continue
          const el = await helpers.createCardElement({
            type: 'picture-entity', entity, camera_view: 'live', show_name: false, show_state: false,
          })
          // Changed its mind while this was building: the next render builds the right one.
          if (this._liveEntityFor(camera) !== entity) continue
          el.hass = this._hass
          this._live[camera.id] = el
          this._liveEntity[camera.id] = entity
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
      this._syncPlayer()
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
      this._syncPlayer()
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

      on('[data-hd]', 'click', (el) => {
        const id = el.dataset.hd
        const camera = config.cameras.find((camera) => camera.id === id)
        if (!camera) return
        if (this._hd.has(id)) this._hd.delete(id)
        else this._hd.add(id)
        el.classList.toggle('on', this._hd.has(id))
        el.setAttribute('aria-pressed', String(this._hd.has(id)))
        this._mountLive({ cameras: [camera] })
      })

      on('[data-settings]', 'click', (el) => this._openSettings(el.dataset.settings))
      on('[data-back]', 'click', () => this._closeSettings())

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
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaCamerasCard])
})()
