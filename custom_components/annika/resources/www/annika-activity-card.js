// Annika activity card.
//
// Who used the entities you list from the Annika app, and when: an initial
// badge (like Home Assistant's own user badge), the name, and the time. The lines come from the integration —
// actor.py writes a `logbook_entry` (domain `annika`) for every action the app
// makes on someone's behalf, see activity.py — and this card shows those and
// nothing else.
//
// Why not the stock Logbook card: it reads the same lines, but the frontend
// renders any logbook line about a `script.*` or `automation.*` entity as a
// bare "Ran" / "Triggered" and drops the message, so on a gate script the one
// thing worth reading never appears. It also mixes in every on/off/started
// line the entity produces, which on a script is three lines per press.
//
// Only actions taken through the app have a name. A keypad, a remote, an
// automation, or someone using Home Assistant directly leaves no line here.
//
// Usage in a dashboard view:
//   type: custom:annika-activity-card
//   title: Actividad          # optional
//   hours_to_show: 168        # optional, default 168 (a week)
//   limit: 30                 # optional, most recent lines shown
//   entities:                 # what to show activity for
//     - script.porton_pulso
//   grid_options:             # optional, sections view only
//     columns: full
;(() => {
  const CARD = 'annika-activity-card'
  const DEFAULT_HOURS = 168
  const DEFAULT_LIMIT = 30

  function entityIds(config) {
    const raw = config.entities ?? (config.entity ? [config.entity] : [])
    const list = (Array.isArray(raw) ? raw : [raw])
      .map((item) => (typeof item === 'string' ? item : item && item.entity))
      .filter((id) => typeof id === 'string' && id.includes('.'))
    if (list.length === 0) throw new Error(`${CARD}: "entities" must list at least one entity id`)
    return list
  }

  // "ejecutado por Facu Spagnuolo" -> "Facu Spagnuolo". The message is built
  // in activity.py as `${action} por ${actor}`.
  function actorOf(message) {
    const at = message.indexOf(' por ')
    return at < 0 ? '' : message.slice(at + 5).trim()
  }

  function initial(name) {
    const first = [...name.trim()][0]
    return first ? first.toLocaleUpperCase() : '?'
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  }

  class AnnikaActivityCard extends HTMLElement {
    constructor() {
      super()
      this._entries = new Map()
      this.attachShadow({ mode: 'open' })
    }

    setConfig(config) {
      const ids = entityIds(config)
      const hours = Number(config.hours_to_show ?? DEFAULT_HOURS)
      const limit = Number(config.limit ?? DEFAULT_LIMIT)
      const changed =
        !this._config ||
        ids.join() !== this._ids.join() ||
        hours !== this._hours
      this._config = config
      this._ids = ids
      this._hours = hours > 0 ? hours : DEFAULT_HOURS
      this._limit = limit > 0 ? limit : DEFAULT_LIMIT
      if (changed) this._resubscribe()
      this._render()
    }

    set hass(hass) {
      const first = !this._hass
      this._hass = hass
      if (first) this._resubscribe()
    }

    connectedCallback() {
      if (this._hass && !this._unsubscribe) this._resubscribe()
    }

    disconnectedCallback() {
      this._stop()
    }

    _stop() {
      const unsubscribe = this._unsubscribe
      this._unsubscribe = undefined
      if (unsubscribe) unsubscribe.then((fn) => fn()).catch(() => {})
    }

    // `logbook/event_stream` is what the stock Logbook card uses: it sends
    // the stored lines for the window first and then each new one as it is
    // written, so the card stays current without polling.
    _resubscribe() {
      if (!this._hass || !this._config || !this.isConnected) return
      this._stop()
      this._entries = new Map()
      this._loaded = false
      this._error = undefined
      const start = new Date(Date.now() - this._hours * 3600 * 1000)
      this._unsubscribe = this._hass.connection
        .subscribeMessage((message) => this._receive(message), {
          type: 'logbook/event_stream',
          start_time: start.toISOString(),
          entity_ids: this._ids,
        })
        .catch((error) => {
          this._error = (error && error.message) || String(error)
          this._render()
        })
      this._render()
    }

    _receive(message) {
      for (const entry of message.events || []) {
        if (entry.domain !== 'annika' || !entry.message) continue
        this._entries.set(`${entry.when}|${entry.entity_id}|${entry.message}`, entry)
      }
      this._loaded = true
      this._render()
    }

    _when(seconds) {
      const hass = this._hass
      const date = new Date(seconds * 1000)
      const timeZone = hass.config && hass.config.time_zone
      const language = (hass.locale && hass.locale.language) || hass.language || 'es'
      const day = (d) => new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
      const time = new Intl.DateTimeFormat(language, { timeZone, hour: '2-digit', minute: '2-digit' }).format(date)
      const today = day(new Date())
      const yesterday = day(new Date(Date.now() - 86400 * 1000))
      if (day(date) === today) return `hoy ${time}`
      if (day(date) === yesterday) return `ayer ${time}`
      const date_ = new Intl.DateTimeFormat(language, { timeZone, weekday: 'short', day: '2-digit', month: '2-digit' }).format(date)
      return `${date_} ${time}`
    }

    _render() {
      if (!this._config) return
      const title = this._config.title ?? 'Actividad'
      const showEntity = this._ids.length > 1
      const entries = [...this._entries.values()].sort((a, b) => b.when - a.when).slice(0, this._limit)

      let body
      if (this._error) {
        body = `<div class="empty">No se pudo cargar la actividad: ${escapeHtml(this._error)}</div>`
      } else if (!this._loaded) {
        body = `<div class="empty">Cargando…</div>`
      } else if (entries.length === 0) {
        const days = Math.round(this._hours / 24)
        body = `<div class="empty">Sin actividad ${days === 1 ? 'en el último día' : `en los últimos ${days} días`}.</div>`
      } else {
        body = entries
          .map((entry) => {
            const actor = actorOf(entry.message) || 'Alguien'
            // Only with more than one entity is "on what" not obvious.
            const detail = showEntity && entry.name ? `<div class="entity">${escapeHtml(entry.name)}</div>` : ''
            return `
              <div class="row">
                <div class="badge" aria-hidden="true">${escapeHtml(initial(actor))}</div>
                <div class="text">
                  <div class="actor">${escapeHtml(actor)}</div>
                  ${detail}
                </div>
                <div class="when">${escapeHtml(this._when(entry.when))}</div>
              </div>`
          })
          .join('')
      }

      this.shadowRoot.innerHTML = `
        <style>
          ha-card { padding: 16px; }
          .title { font-size: var(--ha-card-header-font-size, 24px); color: var(--ha-card-header-color, var(--primary-text-color)); margin: 0 0 8px; line-height: 1.3; }
          .row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--divider-color); }
          .row:last-child { border-bottom: none; }
          /* Same colors as Home Assistant's user badge (ha-user-badge), so
             it follows the theme the way the stock logbook avatars do. */
          .badge { flex: none; width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background-color: var(--light-primary-color); color: var(--text-light-primary-color, var(--primary-text-color)); font-size: 12px; font-weight: 500; }
          .text { flex: 1; min-width: 0; }
          .actor { color: var(--primary-text-color); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .entity { color: var(--secondary-text-color); font-size: 0.9em; }
          .when { color: var(--secondary-text-color); font-size: 0.9em; white-space: nowrap; }
          .empty { color: var(--secondary-text-color); padding: 8px 0; }
        </style>
        <ha-card>
          ${title ? `<div class="title">${escapeHtml(title)}</div>` : ''}
          ${body}
        </ha-card>`
    }

    getCardSize() {
      return 3
    }

    getGridOptions() {
      return { columns: 'full', min_rows: 2 }
    }

    getLayoutOptions() {
      return { grid_columns: 'full' }
    }
  }

  // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaActivityCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Activity',
    description: 'Who did what from the Annika app on the listed entities, over the last days.',
  })
})()
