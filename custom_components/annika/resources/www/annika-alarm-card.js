// Annika alarm card.
//
// Layout:
//   Top row, three columns:
//     1. Alarm panel
//     2. Alarm automations (optional, 2 per row) + logbook of the alarm entity
//     3. Sensors (motion_sensors), optionally Door Sensors (door_sensors,
//        only rendered when non-empty) — tiles laid out 2 per row. Sirens
//        go under the logbook in column 2 by default, also 2 per row — see
//        sirens_position
//   Bottom row, full width:
//     Activity: heading + history-graph of the alarm entity
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color?, toggle? }`, mixable in
// the same list.
//
// Motion and door sensors can carry a `toggle` — a control on the tile for
// some *other* entity, typically the helper an automation checks to decide
// whether that sensor takes part in arming the alarm. The tile still shows
// the sensor's own state. `toggle` takes `{ entity?, style?, color? }`; see
// annika-common.js for the four styles and annika-entity-toggle-feature.js
// for what they look like.
//
// When the Annika integration is configured with `alarm_sensors`, it creates
// that switch for every sensor itself and the card finds it on its own — no
// `toggle` in the dashboard YAML, no input_boolean helpers to keep. Writing
// `toggle` by hand still overrides whatever was found, and `toggle: false`
// is how a sensor opts out of the checkbox entirely.
//
// Sirens sit under the logbook by default. `sirens_position: sensors` moves
// them to the end of the sensor column instead, under Movimiento and Puertas,
// where they get a heading of their own (`headings.sirens`).
//
// Sirens are plain tiles by default, two per row like the sensors. Give one
// a `toggle` to make it switchable from the card; a toggle that names no
// entity controls the siren itself, so `toggle: { style: switch }` is all it
// needs — and that spelling gets Home Assistant's own toggle feature, the
// same control a light tile has. `inline-switch` is the one style wide enough
// to need a full row, so a siren using it gets one.
//
// Usage in a dashboard view:
//   type: custom:annika-alarm-card
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   logbook_hours: 96    # optional, hours of logbook to show (default 96)
//   history_hours: 72    # optional, hours of timeline to show (default 72)
//   logbook_height: 420  # optional, px height of the logbook (default 420)
//   color: primary       # optional, tile color for every tile (default);
//                        # use `state` for Home Assistant's state coloring
//   headings:            # optional, section titles (English by default)
//     activity: Actividad   # over the logbook
//     history: Historial    # over the timeline
//     motion: Movimiento
//     doors: Puertas
//     sirens: Sirenas       # only shown with sirens_position: sensors
//   sirens_position: activity   # optional: activity (default, under the
//                               # logbook) or sensors (end of the sensor
//                               # column)
//   alarm:
//     entity: alarm_control_panel.home_alarm
//     name: Alarm
//     states: [arm_away, arm_night, arm_vacation]
//   automations:         # optional, rendered as toggle tiles above the logbook
//     - entity: automation.alarm_night
//       name: Alarm Night
//     - automation.alarm_away
//   motion_sensors:
//     - entity: binary_sensor.main_bedroom_motion_sensor_motion_detection
//       name: Main Bedroom Sensor
//       toggle: input_boolean.main_bedroom_sensor_armed   # optional
//     - entity: binary_sensor.hall_motion
//       toggle: false        # no checkbox, even if Annika made a switch
//   door_sensors:
//     - binary_sensor.front_door
//     - entity: binary_sensor.garage_door
//       toggle:
//         entity: input_boolean.garage_door_armed
//         style: checkbox    # optional: inline (default), inline-switch,
//         color: green       #           checkbox, switch
//   sirens:
//     - entity: switch.kitchen_siren
//       name: Kitchen Siren        # a plain tile, half a row
//     - entity: switch.garage_siren
//       toggle: { style: switch }  # HA's own toggle, like a light tile
;(() => {
  const CARD = 'annika-alarm-card'

  const DEFAULT_LOGBOOK_HOURS = 96
  const DEFAULT_HISTORY_HOURS = 72
  const DEFAULT_LOGBOOK_HEIGHT = 420
  // Same default as every other Annika card: one uniform surface instead of a
  // mix of per-state colors. `color: state` gives HA's state coloring back.
  const DEFAULT_COLOR = 'primary'

  // English by default so a unit that says nothing keeps reading the same;
  // override per unit with `headings:` — see the usage block above.
  const DEFAULT_HEADINGS = {
    activity: 'Activity',   // over the logbook
    history: 'History',     // over the timeline
    motion: 'Sensors',
    doors: 'Doors',
    sirens: 'Sirens',   // only shown when the sirens sit in the sensor column
  }

  // Where the sirens go. Two sensible homes, and which one reads better
  // depends on how long the sensor column already is on a given unit.
  const SIREN_POSITIONS = ['activity', 'sensors']
  const DEFAULT_SIREN_POSITION = 'activity'

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  // How many sirens fit on a row. Two, like the sensor tiles, unless one of
  // them carries an `inline-switch` — that control sits *inside* the tile's
  // row and takes nearly half of it, so at half width there is nothing left
  // for the name. Every other style stays comfortable at two per row: the
  // checkboxes are small, and `switch` gets a row of its own inside the tile
  // either way. Derived rather than configured, so choosing the control is
  // the only decision to make.
  function sirenColumns(sirens) {
    return sirens.some((item) => item.toggle && item.toggle.style === 'inline-switch') ? 1 : 2
  }

  class AnnikaAlarmCard extends HTMLElement {
    setConfig(config) {
      if (!config.alarm || !config.alarm.entity) {
        throw new Error(`${CARD}: "alarm.entity" is required`)
      }
      const { normalizeItem, normalizeItems } = annika()

      this._config = config
      this._alarm = { ...normalizeItem(config.alarm, CARD), states: config.alarm.states }
      this._automations = normalizeItems(config.automations || [], CARD, 'automations')
      this._motionSensors = normalizeItems(config.motion_sensors, CARD, 'motion_sensors')
      this._doorSensors = normalizeItems(config.door_sensors || [], CARD, 'door_sensors')
      this._sirens = normalizeItems(config.sirens, CARD, 'sirens')

      this._sirenPosition = config.sirens_position || DEFAULT_SIREN_POSITION
      if (!SIREN_POSITIONS.includes(this._sirenPosition)) {
        throw new Error(`${CARD}: "sirens_position" must be one of ${SIREN_POSITIONS.join(', ')}`)
      }

      this._render()
    }

    set hass(hass) {
      const previous = this._hass
      this._hass = hass

      // The participation switches are created by the Annika integration
      // after Home Assistant finishes starting, which can land after this
      // card first rendered. A registry change is the cheap signal that new
      // entities exist, so the card picks them up without a page reload.
      if (previous && this._cards && previous.entities !== hass.entities) {
        this._cards = undefined
        this._render()
        return
      }

      if (this._cards) {
        for (const card of this._cards) card.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const sensors =
        this._motionSensors.length + this._doorSensors.length + this._sirens.length
      return Math.max(6, Math.ceil(sensors / 2) + 6)
    }

    getGridOptions() {
      return {
        columns: 'full',
      }
    }

    getLayoutOptions() {
      return {
        grid_columns: 'full',
      }
    }

    // switch entity id, indexed by the sensor it belongs to. Built once per
    // render rather than scanned per sensor.
    _participationToggles() {
      const index = new Map()
      for (const state of Object.values(this._hass?.states || {})) {
        const source = state.attributes?.source_entity_id
        if (source && state.entity_id.startsWith('switch.')) index.set(source, state.entity_id)
      }
      return index
    }

    async _render() {
      if (!this._hass || !this._config || this._cards) return

      const { tileConfig, headingConfig, gridConfig, HEADING_CSS, appendHeading } = annika()
      const helpers = await window.loadCardHelpers()
      const {
        logbook_hours: logbookHours = DEFAULT_LOGBOOK_HOURS,
        history_hours: historyHours = DEFAULT_HISTORY_HOURS,
        logbook_height: logbookHeight = DEFAULT_LOGBOOK_HEIGHT,
      } = this._config

      const headings = { ...DEFAULT_HEADINGS, ...(this._config.headings || {}) }

      const color = this._config.color === undefined ? DEFAULT_COLOR : this._config.color

      // Tiles are laid out two per row so they take half the column width
      // instead of stretching across the whole column. The card-level color is
      // a default: an item's own `color` still wins.
      const tileGrid = (items, options) =>
        gridConfig(items.map((item) => tileConfig({ color, ...item }, options)), 2)

      // The Annika integration creates one participation switch per alarm
      // sensor and tags it with the sensor it belongs to, so a sensor that
      // has one gets its toggle without naming it in the dashboard YAML.
      // An explicit `toggle` in the config still wins.
      const toggles = this._participationToggles()
      const withToggle = (item) => {
        // `!== undefined` rather than a truth test, so `toggle: false` means
        // what it says. A truth test would auto-pair the sensor anyway and
        // leave no way at all to ask for a sensor without a checkbox.
        if (item.toggle !== undefined || !toggles.has(item.entity)) return item
        return { ...item, toggle: { entity: toggles.get(item.entity), color: item.color } }
      }

      // Plain tiles, two per row like the sensors — see sirenColumns for the
      // one style that needs more room.
      const sirenGrid = () =>
        gridConfig(
          this._sirens.map((item) => tileConfig({ color, ...item })),
          sirenColumns(this._sirens),
        )

      const sensorCards = [headingConfig(headings.motion), tileGrid(this._motionSensors.map(withToggle))]
      if (this._doorSensors.length > 0) {
        sensorCards.push(headingConfig(headings.doors), tileGrid(this._doorSensors.map(withToggle)))
      }
      // In the sensor column the sirens land under Movimiento and Puertas, so
      // they get a heading of their own — without one they read as more doors.
      // Under the logbook they are the only thing there and do not need it.
      if (this._sirens.length > 0 && this._sirenPosition === 'sensors') {
        sensorCards.push(headingConfig(headings.sirens), sirenGrid())
      }

      const alarmConfig = {
        type: 'vertical-stack',
        cards: [
          {
            type: 'alarm-panel',
            entity: this._alarm.entity,
            name: this._alarm.name,
            states: this._alarm.states,
          },
        ],
      }

      const logbookConfig = {
        type: 'logbook',
        entities: [this._alarm.entity],
        hours_to_show: logbookHours,
      }

      const sensorsConfig = {
        type: 'vertical-stack',
        cards: sensorCards,
      }

      const activityConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig(headings.history),
          {
            type: 'history-graph',
            // No title of its own: the heading above already names the
            // section, and the card's title would repeat it inside the box.
            refresh_interval: 60,
            hours_to_show: historyHours,
            entities: [{ entity: this._alarm.entity, name: this._alarm.name }],
          },
        ],
      }

      this._cards = []
      const build = (cfg) => {
        const element = helpers.createCardElement(cfg)
        element.hass = this._hass
        this._cards.push(element)
        return element
      }

      // The middle column is assembled here rather than handed to a
      // vertical-stack so the logbook can be wrapped in an element of ours.
      // The logbook grows without bound otherwise, and capping it by styling
      // Home Assistant's own `hui-logbook-card` tag would break silently the
      // day that element is renamed.
      const logbookColumn = document.createElement('div')
      logbookColumn.className = 'annika-alarm-column'
      if (this._automations.length > 0) {
        logbookColumn.appendChild(build(tileGrid(this._automations, { features: [{ type: 'toggle' }] })))
      }
      this._cards.push(
        await appendHeading(logbookColumn, helpers, this._hass, headings.activity, { style: 'title' }),
      )

      const logbook = document.createElement('div')
      logbook.className = 'annika-logbook'
      logbook.appendChild(build(logbookConfig))
      logbookColumn.appendChild(logbook)

      // Sirens sit under the logbook rather than at the end of the sensor
      // column: there are one or two of them, and the sensor column is long.
      //
      // A plain tile by default — no control, two per row, exactly like every
      // sensor above them, so the column reads as one thing. A siren that
      // should be switchable from here says so with `toggle:`, and since a
      // toggle that names no entity of its own controls the tile's entity,
      // `toggle: { style: switch }` is the whole of it.
      if (this._sirens.length > 0 && this._sirenPosition === 'activity') {
        logbookColumn.appendChild(build(sirenGrid()))
      }

      const columns = [build(alarmConfig), logbookColumn, build(sensorsConfig)]
      const activity = build(activityConfig)

      this.innerHTML = `
        <style>
          ${HEADING_CSS}
          .annika-alarm-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            align-items: start;
          }
          .annika-alarm-grid > * {
            min-width: 0;
          }
          .annika-alarm-column {
            display: flex;
            flex-direction: column;
            gap: var(--ha-section-row-gap, 8px);
          }
          .annika-logbook {
            height: ${logbookHeight}px;
          }
          /* Whatever card lands inside, no tag names involved. */
          .annika-logbook > * {
            display: block;
            height: 100%;
          }
          .annika-alarm-activity {
            margin-top: 16px;
          }
          @media (max-width: 800px) {
            .annika-alarm-grid { grid-template-columns: 1fr; }
          }
        </style>
      `
      const grid = document.createElement('div')
      grid.className = 'annika-alarm-grid'
      for (const column of columns) grid.appendChild(column)
      this.appendChild(grid)

      activity.classList.add('annika-alarm-activity')
      this.appendChild(activity)
    }
  }

  customElements.define('annika-alarm-card', AnnikaAlarmCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-alarm-card',
    name: 'Annika Alarm',
    description:
      'Alarm panel, alarm automations and logbook, sensors/sirens (with optional door sensors) in 3 columns, plus a full-width activity timeline.',
  })
})()
