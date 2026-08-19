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
// Usage in a dashboard view:
//   type: custom:annika-alarm-card
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   logbook_hours: 96    # optional, hours of logbook to show (default 96)
//   history_hours: 72    # optional, hours of timeline to show (default 72)
//   logbook_height: 420  # optional, px height of the logbook (default 420)
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
      this._hass = hass
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

    async _render() {
      if (!this._hass || !this._config || this._cards) return

      const { tileConfig, headingConfig, gridConfig } = annika()
      const helpers = await window.loadCardHelpers()
      const {
        logbook_hours: logbookHours = DEFAULT_LOGBOOK_HOURS,
        history_hours: historyHours = DEFAULT_HISTORY_HOURS,
        logbook_height: logbookHeight = DEFAULT_LOGBOOK_HEIGHT,
      } = this._config

      // Tiles are laid out two per row so they take half the column width
      // instead of stretching across the whole column.
      const tileGrid = (items, options) => gridConfig(items.map((item) => tileConfig(item, options)), 2)

      const sensorCards = [headingConfig('Sensors'), tileGrid(this._motionSensors)]
      if (this._doorSensors.length > 0) {
        sensorCards.push(headingConfig('Doors'), tileGrid(this._doorSensors))
      }
      sensorCards.push(headingConfig('Sirens'), tileGrid(this._sirens))

      const logbookCards = []
      if (this._automations.length > 0) {
        logbookCards.push(tileGrid(this._automations, { features: [{ type: 'toggle' }] }))
      }
      logbookCards.push({
        type: 'logbook',
        entities: [this._alarm.entity],
        hours_to_show: logbookHours,
      })

      const columnConfigs = [
        {
          type: 'vertical-stack',
          cards: [
            {
              type: 'alarm-panel',
              entity: this._alarm.entity,
              name: this._alarm.name,
              states: this._alarm.states,
            },
          ],
        },
        {
          type: 'vertical-stack',
          cards: logbookCards,
        },
        {
          type: 'vertical-stack',
          cards: sensorCards,
        },
      ]

      const activityConfig = {
        type: 'vertical-stack',
        cards: [
          headingConfig('Activity'),
          {
            type: 'history-graph',
            title: 'Timeline',
            refresh_interval: 60,
            hours_to_show: historyHours,
            entities: [{ entity: this._alarm.entity, name: this._alarm.name }],
          },
        ],
      }

      const build = (cfg) => {
        const element = helpers.createCardElement(cfg)
        element.hass = this._hass
        return element
      }

      const columns = columnConfigs.map(build)
      const activity = build(activityConfig)
      this._cards = [...columns, activity]

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
          .annika-alarm-grid hui-logbook-card {
            display: block;
            height: ${logbookHeight}px;
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
