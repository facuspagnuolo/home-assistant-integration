// Annika alarm card.
//
// Layout:
//   Top row, three columns:
//     1. Alarm panel
//     2. Alarm automations (optional, 2 per row) + logbook of the alarm entity
//     3. Sensors (motion_sensors), optionally Door Sensors (door_sensors,
//        only rendered when non-empty, placed between motion and sirens),
//        then Sirens — all tiles laid out 2 per row
//   Bottom row, full width:
//     Activity: heading + history-graph of the alarm entity
//
// Entities use the shared Annika shape (see annika-common.js): either a
// bare entity id or `{ entity, name?, icon?, color?, toggle? }`, mixable in
// the same list.
//
// Motion and door sensors can optionally carry a `toggle` entity — an
// `input_boolean` helper that gets its own switch under the sensor tile,
// looking exactly like the toggle on an automation tile. The tile still
// shows the sensor's state; the switch flips the helper, so an automation
// can check it to decide whether that sensor participates in arming the
// alarm. Use `toggle: { entity, color }` to give the switch its own color.
// See annika-entity-toggle-feature.js.
//
// When the Annika integration is configured with `alarm_sensors`, it creates
// that switch for every sensor itself and the card finds it on its own — no
// `toggle` in the dashboard YAML, no input_boolean helpers to keep. Writing
// `toggle` by hand still overrides whatever was found.
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
//   door_sensors:
//     - binary_sensor.front_door
//     - entity: binary_sensor.garage_door
//       toggle:
//         entity: input_boolean.garage_door_armed
//         color: green
//   sirens:
//     - entity: switch.kitchen_siren
//       name: Kitchen Siren
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
  }

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
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

      const { tileConfig, headingConfig, gridConfig } = annika()
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
        if (item.toggle || !toggles.has(item.entity)) return item
        return { ...item, toggle: { entity: toggles.get(item.entity), color: item.color } }
      }

      const sensorCards = [headingConfig(headings.motion), tileGrid(this._motionSensors.map(withToggle))]
      if (this._doorSensors.length > 0) {
        sensorCards.push(headingConfig(headings.doors), tileGrid(this._doorSensors.map(withToggle)))
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
      logbookColumn.appendChild(build(headingConfig(headings.activity)))

      const logbook = document.createElement('div')
      logbook.className = 'annika-logbook'
      logbook.appendChild(build(logbookConfig))
      logbookColumn.appendChild(logbook)

      // Sirens sit under the logbook rather than at the end of the sensor
      // column: there are one or two of them, and the sensor column is long.
      if (this._sirens.length > 0) {
        // The same `ha-control-switch` Home Assistant's native toggle feature
        // renders, but in the tile's own row: the native one always takes a
        // row of its own, and this tile reads better as one. Full width and no
        // heading, so it sits as the last row of the activity column.
        logbookColumn.appendChild(
          build(
            gridConfig(
              this._sirens.map((item) =>
                tileConfig(
                  { color, ...item },
                  {
                    features: [
                      {
                        type: 'custom:annika-entity-toggle-feature',
                        entity: item.toggle?.entity || item.entity,
                        style: 'inline-switch',
                      },
                    ],
                  },
                ),
              ),
              1,
            ),
          ),
        )
      }

      const columns = [build(alarmConfig), logbookColumn, build(sensorsConfig)]
      const activity = build(activityConfig)

      this.innerHTML = `
        <style>
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
