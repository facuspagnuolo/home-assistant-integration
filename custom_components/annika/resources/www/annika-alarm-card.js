// Annika alarm card.
//
// Three-column layout:
//   1. Alarm panel
//   2. Activity: heading + history-graph of the alarm entity
//   3. Sensors (motion_sensors), optionally Door Sensors (door_sensors,
//      only rendered when non-empty, placed between motion and sirens),
//      then Sirens
//
// Usage in a dashboard view:
//   type: custom:annika-alarm-card
//   alarm:
//     entity: alarm_control_panel.home_alarm
//     name: Alarm
//     states: [arm_away, arm_night, arm_vacation]
//   motion_sensors:
//     - entity: binary_sensor.main_bedroom_motion_sensor_motion_detection
//       name: Main Bedroom Sensor
//   door_sensors:
//     - entity: binary_sensor.front_door
//       name: Front Door
//   sirens:
//     - entity: switch.kitchen_siren
//       name: Kitchen Siren
;(() => {
  function tileConfig(item) {
    return {
      type: 'tile',
      entity: item.entity,
      name: item.name,
      icon: item.icon,
      hide_state: false,
      vertical: false,
      features_position: 'bottom',
    }
  }

  function headingConfig(text) {
    return { type: 'heading', heading: text, heading_style: 'title' }
  }

  class AnnikaAlarmCard extends HTMLElement {
    setConfig(config) {
      if (!config.alarm || !config.alarm.entity) {
        throw new Error('annika-alarm-card: "alarm.entity" is required')
      }
      if (!Array.isArray(config.motion_sensors) || !Array.isArray(config.sirens)) {
        throw new Error('annika-alarm-card: "motion_sensors" and "sirens" must be lists')
      }
      this._config = config
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._columns) {
        for (const column of this._columns) column.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const sensors = (this._config?.motion_sensors?.length || 0) + (this._config?.door_sensors?.length || 0)
      return Math.max(6, sensors + (this._config?.sirens?.length || 0) + 4)
    }

    async _render() {
      if (!this._hass || !this._config || this._columns) return

      const helpers = await window.loadCardHelpers()
      const { alarm, motion_sensors: motionSensors, sirens, door_sensors: doorSensors = [] } = this._config

      const sensorCards = [headingConfig('Sensors'), ...motionSensors.map(tileConfig)]
      if (doorSensors.length > 0) {
        sensorCards.push(headingConfig('Door Sensors'), ...doorSensors.map(tileConfig))
      }
      sensorCards.push(headingConfig('Sirens'), ...sirens.map(tileConfig))

      const columnConfigs = [
        {
          type: 'vertical-stack',
          cards: [
            {
              type: 'alarm-panel',
              entity: alarm.entity,
              name: alarm.name,
              states: alarm.states,
            },
          ],
        },
        {
          type: 'vertical-stack',
          cards: [
            headingConfig('Activity'),
            {
              type: 'history-graph',
              title: 'Timeline',
              refresh_interval: 60,
              hours_to_show: 72,
              entities: [{ entity: alarm.entity, name: alarm.name }],
            },
          ],
        },
        {
          type: 'vertical-stack',
          cards: sensorCards,
        },
      ]

      this._columns = columnConfigs.map((cfg) => {
        const element = helpers.createCardElement(cfg)
        element.hass = this._hass
        return element
      })

      this.innerHTML = `
        <style>
          .annika-alarm-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
          }
          @media (max-width: 800px) {
            .annika-alarm-grid { grid-template-columns: 1fr; }
          }
        </style>
      `
      const grid = document.createElement('div')
      grid.className = 'annika-alarm-grid'
      for (const column of this._columns) grid.appendChild(column)
      this.appendChild(grid)
    }
  }

  customElements.define('annika-alarm-card', AnnikaAlarmCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-alarm-card',
    name: 'Annika Alarm',
    description: 'Alarm panel, activity history, and sensors/sirens (with optional door sensors) laid out in 3 columns.',
  })
})()
