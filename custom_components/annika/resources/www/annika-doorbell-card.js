// Annika doorbell card: the doorbell's camera, a button to listen and a button to
// talk, and who is told when someone rings (see doorbells.py).
//
// Usage in a dashboard view:
//   type: custom:annika-doorbell-card
//   entity: sensor.annika_doorbells
//   name: Doorbell              # optional
//   language: es                # optional; by default the Home Assistant language
//
// Each doorbell is a tile like a camera's: the live view, its name, the
// detection icons, the speaker and microphone buttons and a gear. The gear opens
// the settings of that doorbell's device (what the camera's gear shows). Who is
// told, and what counts as nobody being home, are the same for every doorbell
// and sit beside the tiles (below them on a phone).
//
// Below the tiles are the clips of the rings that were recorded (see doorbells.py):
// one is kept when someone rings and nobody is home (what is recorded when is set in
// the Recording panel), and they are deleted by themselves after the days it says.
//
// Talking: the live view is not Home Assistant's picture card but a WebRTC
// connection of its own, through Home Assistant's `camera/webrtc/offer` (the
// same one its own card uses), that also offers the doorbell an audio track to
// send. The speaker and the microphone both start off:
//
//   speaker     the video's sound, off until it is asked for;
//   microphone  nothing is captured until the first time it is turned on (that is
//               when the browser asks), and turning it off releases it, so the
//               browser's recording indicator goes away with it.
//
// The microphone needs HTTPS (a browser rule). It is turned off when the page is
// hidden or the card leaves the screen, and after `talk.auto_off_seconds` when
// that is on. If the doorbell cannot be played this way the live view falls back
// to Home Assistant's own card, without the microphone.
;(() => {
  const CARD = 'annika-doorbell-card'
  const SERVICE_DOMAIN = 'annika'

  const TEXTS = {
    en: {
      missing: 'Entity not found: {entity}',
      doorbell: 'Doorbell',
      doorbells: 'Doorbells',
      notifications: 'Notifications',
      device: 'Who',
      at_home: 'At home',
      away: 'Away',
      test: 'Test',
      devices: 'Devices',
      devices_sub: 'Paired tablets',
      users: 'Users',
      users_sub: 'People of the Annika app',
      presence: 'Away when none of these is home',
      add_person: 'Add person…',
      remove: 'Remove',
      now_away: 'Now: away · {home} of {total} home',
      now_home: 'Now: at home · {home} of {total} home',
      no_notification: 'Notifications need a notify_view in the configuration.',
      talk: 'Talk',
      mute_speaker: 'Mute the speaker while talking',
      auto_off: 'Turn the microphone off after',
      sec: 'sec',
      speaker: 'Speaker',
      speaker_on: 'Mute the speaker',
      speaker_off: 'Listen',
      speaker_locked: 'The speaker is muted while talking',
      mic: 'Microphone',
      mic_on: 'Mute the microphone',
      mic_off: 'Talk',
      connecting: 'Connecting…',
      cannot_talk: 'This doorbell cannot be talked to',
      mic_denied: 'The microphone is not allowed in this browser',
      mic_insecure: 'The microphone needs a secure (HTTPS) connection',
      mic_error: 'The microphone could not be started',
      visitor: 'Visitor',
      person: 'Person',
      vehicle: 'Vehicle',
      animal: 'Animal',
      motion: 'Motion',
      settings: 'Settings',
      back: 'Back',
      no_settings: 'This doorbell has no settings to show',
      confirm_restart: 'Restart this device?',
      confirm_siren: 'Turn the siren on?',
      recording: 'Recording',
      record_when: 'Record a clip when someone rings',
      keep_days: 'Keep clips for',
      days: 'days',
      clips: 'Clips',
      no_clips: 'No clips yet',
      ring: 'Ring',
      notified: 'Notified',
      just_now: 'just now',
      delete: 'Delete',
      close: 'Close',
      loading: 'Loading…',
      cannot_play: 'This clip cannot be played',
    },
    es: {
      missing: 'No se encontró la entidad: {entity}',
      doorbell: 'Timbre',
      doorbells: 'Timbres',
      notifications: 'Notificaciones',
      device: 'Quién',
      at_home: 'En casa',
      away: 'Fuera',
      test: 'Probar',
      devices: 'Dispositivos',
      devices_sub: 'Tablets emparejadas',
      users: 'Usuarios',
      users_sub: 'Personas de la app de Annika',
      presence: 'Fuera si ninguno de estos está en casa',
      add_person: 'Agregar persona…',
      remove: 'Quitar',
      now_away: 'Ahora: fuera · {home} de {total} en casa',
      now_home: 'Ahora: en casa · {home} de {total} en casa',
      no_notification: 'Las notificaciones necesitan notify_view en la configuración.',
      talk: 'Hablar',
      mute_speaker: 'Silenciar el parlante mientras se habla',
      auto_off: 'Apagar el micrófono después de',
      sec: 'seg',
      speaker: 'Parlante',
      speaker_on: 'Silenciar el parlante',
      speaker_off: 'Escuchar',
      speaker_locked: 'El parlante se silencia mientras se habla',
      mic: 'Micrófono',
      mic_on: 'Silenciar el micrófono',
      mic_off: 'Hablar',
      connecting: 'Conectando…',
      cannot_talk: 'No se puede hablar por este timbre',
      mic_denied: 'El micrófono no está permitido en este navegador',
      mic_insecure: 'El micrófono necesita una conexión segura (HTTPS)',
      mic_error: 'No se pudo iniciar el micrófono',
      visitor: 'Visita',
      person: 'Persona',
      vehicle: 'Vehículo',
      animal: 'Animal',
      motion: 'Movimiento',
      settings: 'Ajustes',
      back: 'Volver',
      no_settings: 'Este timbre no tiene ajustes para mostrar',
      confirm_restart: '¿Reiniciar este dispositivo?',
      confirm_siren: '¿Encender la sirena?',
      recording: 'Grabación',
      record_when: 'Grabar un clip cuando suena el timbre',
      keep_days: 'Guardar los clips',
      days: 'días',
      clips: 'Clips',
      no_clips: 'Todavía no hay clips',
      ring: 'Timbre',
      notified: 'Avisado',
      just_now: 'recién',
      delete: 'Borrar',
      close: 'Cerrar',
      loading: 'Cargando…',
      cannot_play: 'No se puede reproducir este clip',
    },
  }

  const TARGETS = ['devices', 'users']
  const WHEN = ['at_home', 'away']
  const KINDS = ['person', 'vehicle', 'animal', 'motion']
  const ICONS = { visitor: 'mdi:bell-ring', person: 'mdi:account', vehicle: 'mdi:car', animal: 'mdi:paw', motion: 'mdi:motion-sensor' }
  // What the settings of a doorbell show, in this order; the rest follows.
  const SETTING_DOMAINS = ['switch', 'light', 'siren', 'select', 'number', 'button', 'update', 'binary_sensor', 'sensor']
  // Entities of the device that are not settings (the streams are the tile).
  const HIDDEN_DOMAINS = ['camera', 'image']
  // The tiles' colour, the one the lights, covers and cameras cards use for theirs.
  const SETTINGS_COLOR = 'primary'
  // How long the browser has to gather its network candidates before the offer goes out.
  const GATHER_MS = 2000
  // A connection that drops is given this long to come back before the live view is given up.
  const DISCONNECTED_MS = 5000

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')

  // A dropdown, drawn like the irrigation card's (see SELECT_CSS in annika-common.js).
  const selectBox = (select) => `<span class="annika-select">${select}</span>`

  const gathered = (pc, ms) =>
    new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve()
      const finish = () => {
        pc.removeEventListener('icegatheringstatechange', check)
        clearTimeout(timer)
        resolve()
      }
      const check = () => {
        if (pc.iceGatheringState === 'complete') finish()
      }
      const timer = setTimeout(finish, ms)
      pc.addEventListener('icegatheringstatechange', check)
    })

  // One doorbell's WebRTC connection: the video and sound it sends, and an audio
  // track of our own for the microphone, which stays empty until it is asked for.
  class Player {
    constructor(hass, entity) {
      this.hass = hass
      this.entity = entity
      this.failed = false
      this.onfail = null
      this._generation = 0
      this._pc = null
      this._audio = null
      this._unsubscribe = null
      this._mic = null
      this._video = null
    }

    // Muted and playing inline: the speaker is something the person turns on.
    get video() {
      if (!this._video) {
        const video = document.createElement('video')
        video.autoplay = true
        video.muted = true
        video.playsInline = true
        video.setAttribute('playsinline', '')
        video.className = 'annika-doorbell-video'
        this._video = video
      }
      return this._video
    }

    // Whether the doorbell agreed to receive what the microphone sends.
    get talkSupported() {
      const direction = this._audio && this._audio.currentDirection
      return !!direction && direction.startsWith('send')
    }

    get micOn() {
      return !!this._mic
    }

    async connect() {
      this.close()
      this.failed = false
      const generation = ++this._generation
      let config = {}
      try {
        config = await this.hass.callWS({ type: 'camera/webrtc/get_client_config', entity_id: this.entity })
      } catch (err) {
        // Home Assistant's defaults.
      }
      if (generation !== this._generation) return
      const pc = new RTCPeerConnection((config && config.configuration) || {})
      this._pc = pc
      pc.addTransceiver('video', { direction: 'recvonly' })
      // sendrecv: the doorbell's own sound comes in, and the microphone's goes out
      // once there is a track to put on it.
      this._audio = pc.addTransceiver('audio', { direction: 'sendrecv' })
      pc.createDataChannel((config && config.dataChannel) || 'dc')
      const stream = new MediaStream()
      pc.addEventListener('track', (event) => {
        stream.addTrack(event.track)
        const video = this.video
        video.srcObject = stream
        const playing = video.play && video.play()
        if (playing && playing.catch) playing.catch(() => {})
      })
      let timer = null
      pc.addEventListener('connectionstatechange', () => {
        if (generation !== this._generation) return
        clearTimeout(timer)
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') this._fail()
        else if (pc.connectionState === 'disconnected') timer = setTimeout(() => this._fail(), DISCONNECTED_MS)
      })
      try {
        await pc.setLocalDescription(await pc.createOffer())
        await gathered(pc, GATHER_MS)
        if (generation !== this._generation) return
        const unsubscribe = await this.hass.connection.subscribeMessage(
          (message) => this._message(pc, generation, message),
          { type: 'camera/webrtc/offer', entity_id: this.entity, offer: pc.localDescription.sdp }
        )
        if (generation !== this._generation) unsubscribe()
        else this._unsubscribe = unsubscribe
      } catch (err) {
        if (generation === this._generation) this._fail()
      }
    }

    _message(pc, generation, message) {
      if (generation !== this._generation) return
      if (message.type === 'answer') {
        pc.setRemoteDescription({ type: 'answer', sdp: message.answer }).catch(() => this._fail())
      } else if (message.type === 'candidate') {
        pc.addIceCandidate(message.candidate).catch(() => {})
      } else if (message.type === 'error') {
        this._fail()
      }
    }

    _fail() {
      if (this.failed) return
      this.failed = true
      this.close()
      if (this.onfail) this.onfail()
    }

    setMuted(muted) {
      const video = this.video
      video.muted = muted
      if (!muted && video.play) {
        const playing = video.play()
        if (playing && playing.catch) playing.catch(() => {})
      }
    }

    // The browser asks for the microphone here, the first time.
    async startMic() {
      if (this._mic) return
      const devices = typeof navigator !== 'undefined' && navigator.mediaDevices
      if (!devices || !devices.getUserMedia || (typeof isSecureContext !== 'undefined' && isSecureContext === false)) {
        const error = new Error('insecure')
        error.name = 'InsecureContext'
        throw error
      }
      if (!this.talkSupported) {
        const error = new Error('cannot talk')
        error.name = 'CannotTalk'
        throw error
      }
      const stream = await devices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      const track = stream.getAudioTracks()[0]
      if (!this._audio || !this.talkSupported) {
        track.stop()
        const error = new Error('cannot talk')
        error.name = 'CannotTalk'
        throw error
      }
      await this._audio.sender.replaceTrack(track)
      this._mic = track
    }

    // Stopping the track is what turns the browser's recording indicator off.
    async stopMic() {
      const track = this._mic
      this._mic = null
      if (track) track.stop()
      if (this._audio) {
        try {
          await this._audio.sender.replaceTrack(null)
        } catch (err) {
          // The connection is already gone.
        }
      }
    }

    close() {
      this._generation += 1
      if (this._unsubscribe) {
        try {
          this._unsubscribe()
        } catch (err) {
          // Already unsubscribed.
        }
        this._unsubscribe = null
      }
      const track = this._mic
      this._mic = null
      if (track) track.stop()
      if (this._pc) {
        this._pc.close()
        this._pc = null
      }
      this._audio = null
      if (this._video) this._video.srcObject = null
    }
  }

  class AnnikaDoorbellCard extends HTMLElement {
    static get Player() {
      return Player
    }

    setConfig(config) {
      if (!config.entity) throw new Error(`${CARD}: "entity" is required`)
      this._config = config
      this._structure = ''
      this._players = {}
      this._fallback = {}
      this._talk = {}
      // The doorbell whose settings are open (replaces the card's content), or null.
      this._settings = null
      this._tiles = {}
      this._playing = null
      this._render()
    }

    connectedCallback() {
      this._onHidden = () => {
        if (typeof document !== 'undefined' && document.hidden) this._allMicsOff()
      }
      if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this._onHidden)
      // Coming back after leaving: the live views were closed, draw them again.
      this._structure = ''
      if (this._config && this._hass) this._render()
    }

    disconnectedCallback() {
      if (typeof document !== 'undefined' && this._onHidden) document.removeEventListener('visibilitychange', this._onHidden)
      this._allMicsOff()
      if (this._playing) {
        this._playing = null
        this._syncPlayer()
      }
      Object.values(this._players || {}).forEach((player) => player.close())
      this._players = {}
    }

    set hass(hass) {
      this._hass = hass
      this._render()
      this._updateSensors()
      this._updateNow()
      if (this._settings) Object.values(this._tiles).forEach((el) => (el.hass = hass))
      Object.values(this._players).forEach((player) => (player.hass = hass))
      Object.values(this._fallback).forEach((el) => (el.hass = hass))
    }

    getCardSize() {
      return 8
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

    _icon(name) {
      return `<ha-icon icon="${name}"></ha-icon>`
    }

    // --- who is home --------------------------------------------------------

    // The people that can be added: those with something that tells where they are.
    _candidates(group) {
      const states = (this._hass && this._hass.states) || {}
      return Object.keys(states)
        .filter((id) => id.startsWith('person.') && !group.includes(id))
        .filter((id) => ((states[id].attributes || {}).device_trackers || []).length > 0)
        .sort((a, b) => this._personName(a).localeCompare(this._personName(b)))
    }

    _personName(id) {
      const state = this._hass && this._hass.states[id]
      return (state && state.attributes && state.attributes.friendly_name) || id
    }

    _nowText(presence, t) {
      const home = presence.people.filter((person) => person.home).length
      return fill(home > 0 ? t.now_home : t.now_away, { home, total: presence.people.length })
    }

    // Who is home changes without the card being drawn again.
    _updateNow() {
      const stateObj = this._stateObj
      const config = stateObj && stateObj.attributes.config
      if (!config) return
      const t = this._texts
      this.querySelectorAll('[data-now]').forEach((el) => {
        el.textContent = this._nowText(config.presence, t)
      })
    }

    // --- talking ------------------------------------------------------------

    _talkState(id) {
      return (this._talk[id] ||= { speaker: false, mic: 'off', message: '', timer: null })
    }

    get _talkSettings() {
      const stateObj = this._stateObj
      return (stateObj && stateObj.attributes.config && stateObj.attributes.config.talk) || {}
    }

    // The sound plays when it was asked for, unless the microphone is on and the speaker is
    // set to stay quiet then (the doorbell's microphone would hear its own speaker).
    _speakerLocked(id) {
      return this._talkState(id).mic === 'on' && this._talkSettings.mute_speaker !== false
    }

    _speakerAudible(id) {
      return this._talkState(id).speaker && !this._speakerLocked(id)
    }

    _applySpeaker(id) {
      const player = this._players[id]
      if (player) player.setMuted(!this._speakerAudible(id))
    }

    _toggleSpeaker(id) {
      if (this._speakerLocked(id)) return
      const talk = this._talkState(id)
      talk.speaker = !talk.speaker
      this._applySpeaker(id)
      this._syncTalk(id)
    }

    async _toggleMic(id) {
      const talk = this._talkState(id)
      if (talk.mic === 'connecting') return
      if (talk.mic === 'on') return this._micOff(id)
      const player = this._players[id]
      talk.mic = 'connecting'
      talk.message = ''
      this._syncTalk(id)
      try {
        if (!player || player.failed) {
          const error = new Error('cannot talk')
          error.name = 'CannotTalk'
          throw error
        }
        await player.startMic()
      } catch (error) {
        talk.mic = 'off'
        talk.message = this._micError(error)
        this._syncTalk(id)
        return
      }
      talk.mic = 'on'
      this._applySpeaker(id)
      const settings = this._talkSettings
      if (settings.auto_off !== false) {
        talk.timer = setTimeout(() => this._micOff(id), (settings.auto_off_seconds || 60) * 1000)
      }
      this._syncTalk(id)
    }

    async _micOff(id) {
      const talk = this._talkState(id)
      clearTimeout(talk.timer)
      talk.timer = null
      const player = this._players[id]
      if (player) await player.stopMic()
      talk.mic = 'off'
      this._applySpeaker(id)
      this._syncTalk(id)
    }

    _allMicsOff() {
      Object.keys(this._talk || {}).forEach((id) => {
        if (this._talk[id].mic !== 'off') this._micOff(id)
      })
    }

    _micError(error) {
      const t = this._texts
      const name = error && error.name
      if (name === 'NotAllowedError' || name === 'SecurityError') return t.mic_denied
      if (name === 'InsecureContext') return t.mic_insecure
      if (name === 'CannotTalk') return t.cannot_talk
      return t.mic_error
    }

    // The buttons are updated in place: drawing the tile again would restart the stream's sound.
    _syncTalk(id) {
      const t = this._texts
      const talk = this._talkState(id)
      const speaker = this.querySelector(`[data-speaker="${CSS.escape(id)}"]`)
      const mic = this.querySelector(`[data-mic="${CSS.escape(id)}"]`)
      const message = this.querySelector(`[data-talk-message="${CSS.escape(id)}"]`)
      const audible = this._speakerAudible(id)
      const locked = this._speakerLocked(id)
      if (speaker) {
        speaker.classList.toggle('on', audible)
        speaker.setAttribute('aria-pressed', String(audible))
        speaker.disabled = locked
        speaker.title = locked ? t.speaker_locked : audible ? t.speaker_on : t.speaker_off
        const icon = speaker.querySelector('ha-icon')
        if (icon) icon.setAttribute('icon', audible ? 'mdi:volume-high' : 'mdi:volume-off')
      }
      if (mic) {
        mic.classList.toggle('on', talk.mic === 'on')
        mic.classList.toggle('busy', talk.mic === 'connecting')
        mic.setAttribute('aria-pressed', String(talk.mic === 'on'))
        mic.title = talk.mic === 'connecting' ? t.connecting : talk.mic === 'on' ? t.mic_on : t.mic_off
        const icon = mic.querySelector('ha-icon')
        if (icon) icon.setAttribute('icon', talk.mic === 'on' ? 'mdi:microphone' : 'mdi:microphone-off')
      }
      if (message) message.textContent = talk.message || ''
    }

    // --- pieces -------------------------------------------------------------

    _doorbellsHtml(config, t) {
      const tiles = config.doorbells.map((doorbell) => this._tileHtml(doorbell, t, true)).join('')
      const heading = config.doorbells.length > 1 ? t.doorbells : t.doorbell
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(heading)}">${escapeHtml(heading)}</div><div class="tiles">${tiles}</div></div>`
    }

    _tileHtml(doorbell, t, gear) {
      const id = escapeHtml(doorbell.id)
      const sensors = { visitor: doorbell.visitor, ...doorbell.sensors }
      const chips = ['visitor', ...KINDS].filter((kind) => sensors[kind]).map((kind) =>
        `<span class="chip${this._sensorOn(sensors[kind]) ? ' on' : ''}" data-sensor-state="${escapeHtml(sensors[kind])}" title="${escapeHtml(t[kind])}">${this._icon(ICONS[kind])}</span>`
      ).join('')
      const talkButtons = `<span class="sep"></span>
        <button class="talk speaker" data-speaker="${id}" aria-pressed="false" aria-label="${escapeHtml(t.speaker)}" title="${escapeHtml(t.speaker_off)}">${this._icon('mdi:volume-off')}</button>
        <button class="talk mic" data-mic="${id}" aria-pressed="false" aria-label="${escapeHtml(t.mic)}" title="${escapeHtml(t.mic_off)}">${this._icon('mdi:microphone-off')}</button>`
      const cog = gear
        ? `<button class="gear" data-settings="${id}" title="${escapeHtml(t.settings)}" aria-label="${escapeHtml(t.settings)}">${this._icon('mdi:cog')}</button>`
        : ''
      return `<ha-card class="tile">
        <div class="live" data-live="${id}"><span class="placeholder">${escapeHtml(doorbell.name)}</span></div>
        <div class="caption"><span>${escapeHtml(doorbell.name)}</span><span class="chips">${chips}${talkButtons}${cog}</span></div>
        <div class="msg" data-talk-message="${id}"></div>
      </ha-card>`
    }

    _notificationsHtml(config, t) {
      const check = (attrs, on) => `<input type="checkbox" class="annika-check" ${attrs}${on ? ' checked' : ''}>`
      const rows = TARGETS.map((target) => {
        const values = config.notifications[target]
        return `<tr>
          <td class="device"><div>${escapeHtml(t[target])}</div><div class="sub">${escapeHtml(t[`${target}_sub`])}</div></td>
          ${WHEN.map((when) => `<td><div class="cell">${check(`data-notify="${target}" data-when="${when === 'at_home' ? 'home' : 'away'}"`, values[when === 'at_home' ? 'home' : 'away'])}</div></td>`).join('')}
          <td class="test"><button class="play" data-test="${target}" aria-label="${escapeHtml(t.test)}">${this._icon('mdi:play')}</button></td>
        </tr>`
      }).join('')
      const people = config.presence.people
      const chips = people.map((person) =>
        `<button class="pill person" data-person-remove="${escapeHtml(person.entity)}" title="${escapeHtml(t.remove)}">${escapeHtml(person.name)}${this._icon('mdi:close')}</button>`
      ).join('')
      const candidates = this._candidates(people.map((person) => person.entity))
      const add = candidates.length
        ? selectBox(`<select class="add" data-person-add><option value="">${escapeHtml(t.add_person)}</option>${candidates.map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(this._personName(id))}</option>`).join('')}</select>`)
        : ''
      const hint = config.notification ? '' : `<div class="muted note">${escapeHtml(t.no_notification)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.notifications)}">${escapeHtml(t.notifications)}</div>
        <ha-card class="panel table"><table class="fires">
          <thead><tr><th>${escapeHtml(t.device)}</th><th>${escapeHtml(t.at_home)}</th><th>${escapeHtml(t.away)}</th><th class="test">${escapeHtml(t.test)}</th></tr></thead>
          <tbody>${rows}</tbody></table></ha-card>
        <ha-card class="panel"><div class="presence"><span>${escapeHtml(t.presence)}</span>${chips}${add}</div>
          <div class="now" data-now>${escapeHtml(this._nowText(config.presence, t))}</div></ha-card>${hint}</div>`
    }

    _talkHtml(config, t) {
      const talk = config.talk
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.talk)}">${escapeHtml(t.talk)}</div>
        <ha-card class="panel"><div class="stack">
          <label class="field"><input type="checkbox" class="annika-check" data-talk="mute_speaker"${talk.mute_speaker ? ' checked' : ''}><span>${escapeHtml(t.mute_speaker)}</span></label>
          <label class="field"><input type="checkbox" class="annika-check" data-talk="auto_off"${talk.auto_off ? ' checked' : ''}><span>${escapeHtml(t.auto_off)}</span>
            <input type="number" data-talk-seconds min="10" max="600" value="${escapeHtml(talk.auto_off_seconds)}"${talk.auto_off ? '' : ' disabled'}><span class="muted">${escapeHtml(t.sec)}</span></label>
        </div></ha-card></div>`
    }

    // --- settings of one doorbell --------------------------------------------
    //
    // Whatever the doorbell's device exposes, drawn the way the cameras card draws
    // a camera's: Home Assistant's own tile card per entity, with the one feature
    // its kind of entity calls for, in a grid, the live view beside them.

    // Config and diagnostic entities are kept on purpose: for a doorbell they are
    // most of its settings (volumes, ringtones, sensitivity...). Only hidden
    // ones go; disabled ones have no state.
    _deviceEntities(doorbell) {
      const registry = (this._hass && this._hass.entities) || {}
      const states = (this._hass && this._hass.states) || {}
      const device = registry[doorbell.entity] && registry[doorbell.entity].device_id
      if (!device) return []
      const rank = (id) => {
        const at = SETTING_DOMAINS.indexOf(id.split('.')[0])
        return at < 0 ? SETTING_DOMAINS.length : at
      }
      return Object.keys(registry)
        .filter((id) => registry[id].device_id === device && !registry[id].hidden && !registry[id].hidden_by && states[id] && !HIDDEN_DOMAINS.includes(id.split('.')[0]))
        .sort((a, b) => rank(a) - rank(b) || this._entityName(a, device).localeCompare(this._entityName(b, device)))
    }

    // The entity's name without the device's name in front of it: inside one
    // doorbell's settings it only takes room.
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
      const doorbell = config.doorbells.find((d) => d.id === this._settings)
      if (!doorbell) return ''
      const empty = this._deviceEntities(doorbell).length === 0
      return `<div class="wide">
        <div class="settings-head">
          <button class="pill back" data-back title="${escapeHtml(t.back)}">${this._icon('mdi:arrow-left')}${escapeHtml(t.back)}</button>
          <div class="sec" data-heading="${escapeHtml(`${doorbell.name} · ${t.settings}`)}">${escapeHtml(doorbell.name)} · ${escapeHtml(t.settings)}</div>
        </div>
        <div class="annika-tile-row settings">
          <div class="live-tile">${this._tileHtml(doorbell, t, false)}</div>
          <span class="settings-tiles" data-settings-tiles></span>
        </div>
        ${empty ? `<div class="muted empty">${escapeHtml(t.no_settings)}</div>` : ''}
      </div>`
    }

    // The tiles are Home Assistant's own cards, built once per entity and put
    // back into place after every render, like the live views.
    async _mountSettings(config) {
      const doorbell = config.doorbells.find((d) => d.id === this._settings)
      if (!doorbell || !window.loadCardHelpers) return
      try {
        const helpers = await window.loadCardHelpers()
        const elements = []
        for (const id of this._deviceEntities(doorbell)) {
          if (!this._tiles[id]) {
            const element = await helpers.createCardElement(this._settingTile(id))
            element.hass = this._hass
            this._tiles[id] = element
          }
          elements.push(this._tiles[id])
        }
        // Went back while these were being built: nothing to put them in.
        const target = this._settings === doorbell.id && this.querySelector('[data-settings-tiles]')
        if (target) target.replaceChildren(...elements)
      } catch (err) {
        // The doorbell's own tile stays.
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

    _bodyElement() {
      if (!this._body) {
        this._body = document.createElement('div')
        this.appendChild(this._body)
      }
      return this._body
    }

    // Which entities the open doorbell's device has: when they change, the settings are drawn again.
    _deviceKey(config) {
      const doorbell = config.doorbells.find((d) => d.id === this._settings)
      return doorbell ? this._deviceEntities(doorbell).join(',') : ''
    }

    _recordingHtml(config, t) {
      const recording = config.recording
      const check = (when) =>
        `<label class="field"><input type="checkbox" class="annika-check" data-rec-when="${when}"${recording[when] ? ' checked' : ''}><span>${escapeHtml(t[when === 'home' ? 'at_home' : 'away'])}</span></label>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.recording)}">${escapeHtml(t.recording)}</div>
        <ha-card class="panel"><div class="stack">
          <div class="presence"><span>${escapeHtml(t.record_when)}</span>${check('home')}${check('away')}</div>
          <label class="field"><span>${escapeHtml(t.keep_days)}</span>
            <input type="number" data-rec-days min="1" max="365" value="${escapeHtml(recording.keep_days)}"><span class="muted">${escapeHtml(t.days)}</span></label>
        </div></ha-card></div>`
    }

    // --- clips ----------------------------------------------------------------

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
              <span class="thumb">${picture}<span class="play-over">${this._icon('mdi:play')}</span>${bell}</span>
              <span class="meta"><span class="what">${this._icon(ICONS.visitor)}${escapeHtml(clip.doorbell)}</span>
              <span class="muted">${escapeHtml(t.ring)} · ${escapeHtml(this._ago(clip.time))}</span></span>
            </button>`
          }).join('')
        : `<div class="muted empty">${escapeHtml(t.no_clips)}</div>`
      return `<div class="wide clips"><div class="sec" data-heading="${escapeHtml(t.clips)}">${escapeHtml(t.clips)}</div><div class="carousel">${body}</div></div>`
    }

    // The player is a modal <dialog> (as in the cameras card): drawn in the browser's top
    // layer, so it fills the screen whatever the page puts around the card, and outside the
    // card's content so drawing the card again does not restart the video.
    _playerHtml(t) {
      const playing = this._playing
      const media = playing.url
        ? `<video src="${escapeHtml(playing.url)}" controls autoplay playsinline></video>`
        : `<div class="status">${escapeHtml(playing.error ? t.cannot_play : t.loading)}</div>`
      return `<div class="top"><span class="title">${escapeHtml(playing.clip.doorbell)} · ${escapeHtml(t.ring)}</span>
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
          if (id) this._service('delete_doorbell_clip', { clip_id: id })
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

    // --- rendering ----------------------------------------------------------

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
      // A doorbell that is no longer in the configuration has no settings to show.
      if (this._settings && !config.doorbells.some((doorbell) => doorbell.id === this._settings)) this._settings = null
      // Who is home is updated in place (see _updateNow); who is on the list is part of the structure.
      const presence = config.presence.people.map((person) => [person.entity, person.name])
      const key = JSON.stringify([
        config.doorbells, config.notifications, config.notification, config.talk, config.recording, presence,
        attrs.clips, attrs.image_base, attrs.media_base, t.clips,
        this._candidates(presence.map(([entity]) => entity)), t.doorbells, t.talk,
        this._settings, this._settings && this._deviceKey(config),
      ])
      if (!force && key === this._structure) return
      this._structure = key

      // Keep the height while the content is rebuilt (the titles arrive a moment later):
      // on a phone a shorter page would scroll itself back to the top.
      const keep = this.offsetHeight
      if (keep) this.style.minHeight = `${keep}px`
      this._bodyElement().innerHTML = `
        <style>
          annika-doorbell-card { display: block; container-type: inline-size; }
          .annika-doorbell { display: block; }
          .annika-doorbell .layout { display: grid; grid-template-columns: minmax(340px, 480px) minmax(0, 1fr); gap: 0 24px; align-items: start; }
          .annika-doorbell .layout > * { min-width: 0; }
          .annika-doorbell .wide { margin-top: 16px; display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
          .annika-doorbell .sec { font-size: 16px; font-weight: 500; padding: 4px 4px 0; color: var(--primary-text-color); }
          .annika-doorbell .annika-heading { display: block; }
          .annika-doorbell ha-card.panel { display: block; padding: 12px 16px; box-sizing: border-box; }
          .annika-doorbell ha-card.panel.table { padding: 4px 8px; overflow-x: auto; }
          .annika-doorbell .muted, .annika-doorbell .sub { color: var(--secondary-text-color); font-size: 13px; }
          .annika-doorbell .note { margin-top: 10px; }
          .annika-doorbell input[type=number] {
            background: var(--secondary-background-color, transparent); color: var(--primary-text-color);
            border: 1px solid var(--divider-color); border-radius: 6px; padding: 4px 6px; font: inherit; font-size: 14px; width: 64px; color-scheme: dark light; }
          .annika-doorbell input:disabled { opacity: .45; }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}
          ${(window.Annika && window.Annika.SELECT_CSS) || ''}

          /* The camera tile of the cameras card. */
          .annika-doorbell .tiles { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
          .annika-doorbell ha-card.tile { display: block; overflow: hidden; }
          .annika-doorbell .live { aspect-ratio: 16 / 9; background: #000; display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); overflow: hidden; }
          .annika-doorbell .live > * { width: 100%; }
          .annika-doorbell .live video { width: 100%; height: 100%; display: block; object-fit: contain; background: #000; }
          .annika-doorbell .caption { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; padding: 8px 12px; gap: 8px; }
          .annika-doorbell .chips { display: inline-flex; align-items: center; gap: 6px; }
          .annika-doorbell .chip { --mdc-icon-size: 18px; display: inline-flex; color: var(--disabled-color); transition: color .2s; }
          .annika-doorbell .chip.on { color: var(--primary-color); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--primary-color) 70%, transparent)); }
          .annika-doorbell .sep { width: 1px; height: 18px; background: var(--divider-color); margin: 0 4px; }
          .annika-doorbell .gear { border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; padding: 4px; margin-left: 2px;
            --mdc-icon-size: 20px; display: inline-flex; border-radius: 50%; }
          .annika-doorbell .gear:hover { color: var(--primary-text-color); }
          .annika-doorbell .msg { color: var(--error-color, #db4437); font-size: 12px; padding: 0 12px; }
          .annika-doorbell .msg:not(:empty) { padding-bottom: 8px; }

          /* Speaker and microphone: the pill of the cameras card's HD button, round, filled when on. */
          .annika-doorbell .talk { --mdc-icon-size: 18px; border: 1px solid var(--divider-color); background: transparent; color: var(--secondary-text-color);
            border-radius: 999px; width: 32px; height: 32px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; padding: 0;
            transition: background-color .15s, color .15s; }
          .annika-doorbell .talk:hover:not(:disabled) { color: var(--primary-text-color); }
          .annika-doorbell .talk.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
          .annika-doorbell .talk:disabled { cursor: default; opacity: .6; }
          .annika-doorbell .talk.busy { opacity: .6; cursor: progress; }
          .annika-doorbell .talk.mic.on { animation: annika-doorbell-live 1.8s ease-in-out infinite; }
          @keyframes annika-doorbell-live { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--primary-color) 45%, transparent); } 50% { box-shadow: 0 0 0 6px transparent; } }
          @media (prefers-reduced-motion: reduce) { .annika-doorbell .talk.mic.on { animation: none; } }
          .annika-doorbell button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

          /* The alarm card's "What fires" table. */
          .annika-doorbell table { width: 100%; border-collapse: collapse; }
          .annika-doorbell th { text-align: left; font-weight: 400; font-size: 13px; color: var(--secondary-text-color); padding: 10px 8px; }
          .annika-doorbell td { padding: 8px; border-top: 1px solid var(--divider-color); vertical-align: middle; }
          .annika-doorbell .cell { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
          .annika-doorbell th.test, .annika-doorbell td.test { text-align: center; width: 64px; }
          .annika-doorbell .play { --mdc-icon-size: 20px; width: 36px; height: 36px; border-radius: 50%; border: 0; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
            background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color); }
          .annika-doorbell .play:active { filter: brightness(.8); }
          .annika-doorbell .field { display: inline-flex; align-items: center; gap: 8px; }
          .annika-doorbell .stack { display: flex; flex-direction: column; gap: 10px; }
          .annika-doorbell .presence { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
          .annika-doorbell .presence > span:first-child { margin-right: 8px; }
          .annika-doorbell .presence .annika-select select { height: 34px; font-size: 13px; }
          .annika-doorbell .now { color: var(--primary-color); font-size: 13px; font-style: italic; margin-top: 10px; }

          /* The pill of the alarm's mode buttons, small. */
          .annika-doorbell .pill { --mdc-icon-size: 16px; display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
            border-radius: 999px; padding: 6px 8px 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
          .annika-doorbell .pill:hover { border-color: rgba(255, 255, 255, .2); }
          .annika-doorbell .pill.back { --mdc-icon-size: 18px; padding: 2px 10px 2px 8px; font-size: 12px; gap: 4px; }

          /* The cameras card's clips: a carousel of thumbnails, played in a full-screen dialog. */
          .annika-doorbell .carousel { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; scroll-snap-type: x proximity; }
          .annika-doorbell .clip { flex: none; width: 220px; background: var(--ha-card-background, var(--card-background-color)); border: 0; border-radius: var(--ha-card-border-radius, 0); padding: 0;
            text-align: left; cursor: pointer; color: inherit; font: inherit; overflow: hidden; scroll-snap-align: start; }
          .annika-doorbell .thumb { position: relative; display: block; aspect-ratio: 16 / 9; background: #000; }
          .annika-doorbell .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
          .annika-doorbell .thumb .play-over { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; --mdc-icon-size: 36px;
            background: linear-gradient(transparent 55%, rgba(0,0,0,.45)); }
          .annika-doorbell .thumb .bell { position: absolute; top: 6px; right: 6px; --mdc-icon-size: 16px; color: var(--warning-color, #f5b335);
            background: rgba(0,0,0,.55); border-radius: 999px; padding: 3px; display: inline-flex; }
          .annika-doorbell .meta { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px 10px; }
          .annika-doorbell .what { display: flex; align-items: center; gap: 6px; font-size: 14px; --mdc-icon-size: 16px; }
          .annika-doorbell .empty { padding: 12px 0; }
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

          .annika-doorbell .settings-head { display: flex; align-items: center; gap: 12px; }
          .annika-doorbell .settings-head .sec { padding-top: 0; flex: 1; min-width: 0; }
          /* The cameras card's tile row: six columns, the live view takes two and the tiles flow beside it. */
          .annika-doorbell .annika-tile-row { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
            column-gap: var(--ha-section-column-gap, 8px); row-gap: var(--ha-section-row-gap, 8px); }
          .annika-doorbell .annika-tile-row > * { min-width: 0; }
          .annika-doorbell .annika-tile-row .settings-tiles { display: contents; }
          .annika-doorbell .annika-tile-row > .live-tile { grid-column: span 2; grid-row: span 4; align-self: start; }

          @container (max-width: 1100px) {
            .annika-doorbell .annika-tile-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .annika-doorbell .annika-tile-row > .live-tile { grid-column: auto; grid-row: span 3; }
          }
          @container (max-width: 800px) {
            .annika-doorbell .layout { grid-template-columns: minmax(0, 1fr); }
            .annika-doorbell .annika-tile-row { grid-template-columns: minmax(0, 1fr); }
            .annika-doorbell .annika-tile-row > .live-tile { grid-column: auto; grid-row: auto; }
            .annika-doorbell ha-card.panel.table { padding: 4px 4px; }
            .annika-doorbell table { table-layout: fixed; }
            .annika-doorbell td, .annika-doorbell th { padding: 8px 3px; }
            .annika-doorbell th:first-child, .annika-doorbell td.device { width: 30%; }
            .annika-doorbell th.test, .annika-doorbell td.test { width: 44px; }
            .annika-doorbell td.device .sub { display: none; }
            .annika-doorbell .play { width: 32px; height: 32px; }
            .annika-doorbell .presence > span:first-child { flex-basis: 100%; margin-right: 0; }
            .annika-doorbell .clip { width: 180px; }
          }
        </style>
        <div class="annika-doorbell">
          ${this._settings
            ? this._settingsHtml(config, t)
            : `<div class="layout"><div class="doorbells">${this._doorbellsHtml(config, t)}</div><div class="general">${this._notificationsHtml(config, t)}${this._recordingHtml(config, t)}${this._talkHtml(config, t)}</div></div>${this._clipsHtml(attrs, t)}`}
        </div>
      `
      this._bind(config, attrs)
      if (this._settings) this._mountSettings(config)
      this._mountLive(this._settings ? { doorbells: config.doorbells.filter((d) => d.id === this._settings) } : config)
      config.doorbells.forEach((doorbell) => this._syncTalk(doorbell.id))
      this._updateSensors()
      this._signImages()
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

    // --- the live view --------------------------------------------------------

    // The streams are built once and moved back into place after every render, so
    // drawing the card again does not restart them.
    async _mountLive(config) {
      for (const doorbell of config.doorbells) {
        const holder = this.querySelector(`[data-live="${CSS.escape(doorbell.id)}"]`)
        if (!holder) continue
        if (this._fallback[doorbell.id]) {
          holder.replaceChildren(this._fallback[doorbell.id])
          continue
        }
        let player = this._players[doorbell.id]
        if (!player) {
          player = new Player(this._hass, doorbell.entity)
          player.onfail = () => this._fellBack(doorbell)
          this._players[doorbell.id] = player
          holder.replaceChildren(player.video)
          this._applySpeaker(doorbell.id)
          player.connect()
        } else {
          holder.replaceChildren(player.video)
          const playing = player.video.play && player.video.play()
          if (playing && playing.catch) playing.catch(() => {})
        }
      }
    }

    // The doorbell could not be played this way: Home Assistant's own card takes over, without the microphone.
    async _fellBack(doorbell) {
      delete this._players[doorbell.id]
      const talk = this._talkState(doorbell.id)
      clearTimeout(talk.timer)
      talk.mic = 'off'
      talk.message = this._texts.cannot_talk
      this._syncTalk(doorbell.id)
      if (!window.loadCardHelpers) return
      try {
        const helpers = await window.loadCardHelpers()
        const el = await helpers.createCardElement({
          type: 'picture-entity', entity: doorbell.entity, camera_view: 'live', show_name: false, show_state: false,
        })
        el.hass = this._hass
        this._fallback[doorbell.id] = el
        const target = this.querySelector(`[data-live="${CSS.escape(doorbell.id)}"]`)
        if (target) target.replaceChildren(el)
      } catch (err) {
        // The placeholder with the doorbell's name stays.
      }
    }

    // --- events ---------------------------------------------------------------

    _bind(config, attrs) {
      const on = (selector, event, handler) =>
        this.querySelectorAll(selector).forEach((el) => el.addEventListener(event, (e) => handler(el, e)))
      const people = () => config.presence.people.map((person) => person.entity)

      on('[data-speaker]', 'click', (el) => this._toggleSpeaker(el.dataset.speaker))
      on('[data-mic]', 'click', (el) => this._toggleMic(el.dataset.mic))
      on('[data-settings]', 'click', (el) => this._openSettings(el.dataset.settings))
      on('[data-back]', 'click', () => this._closeSettings())

      on('[data-notify]', 'change', (el) => this._service('set_doorbell_notification', { target: el.dataset.notify, [el.dataset.when]: el.checked }))
      on('[data-test]', 'click', (el) => this._service('test_doorbell_notification', { target: el.dataset.test }))
      on('[data-person-remove]', 'click', (el) =>
        this._service('set_doorbell_presence', { people: people().filter((entity) => entity !== el.dataset.personRemove) }))
      on('select[data-person-add]', 'change', (el) => {
        if (el.value) this._service('set_doorbell_presence', { people: [...people(), el.value] })
      })

      on('[data-rec-when]', 'change', (el) => this._service('set_doorbell_recording', { [el.dataset.recWhen]: el.checked }))
      on('[data-rec-days]', 'change', (el) => {
        if (el.value !== '') this._service('set_doorbell_recording', { keep_days: Number(el.value) })
      })
      on('[data-clip]', 'click', (el) => {
        const clip = (attrs.clips || []).find((c) => c.id === el.dataset.clip)
        if (clip) this._play(clip, attrs)
      })

      on('[data-talk]', 'change', (el) => this._service('set_doorbell_talk', { [el.dataset.talk]: el.checked }))
      on('[data-talk-seconds]', 'change', (el) => {
        if (el.value !== '') this._service('set_doorbell_talk', { auto_off_seconds: Number(el.value) })
      })
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaDoorbellCard])
})()
