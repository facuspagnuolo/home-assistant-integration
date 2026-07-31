// Annika cameras card.
//
// Renders a list of cameras as native picture-glance cards, arranged in a
// grid (3 per row by default). Each camera's motion/person/vehicle/animal
// sensors are all optional — only the ones actually given in config (and
// present in hass.states) are shown; nothing is hardcoded to always appear.
//
// Usage in a dashboard view:
//   type: custom:annika-cameras-card
//   columns: 3
//   cameras:
//     - camera: camera.e1_outdoor_se_poe_fluent
//       title: E1
//       motion: binary_sensor.e1_outdoor_se_poe_motion
//       person: binary_sensor.e1_outdoor_se_poe_person
//       vehicle: binary_sensor.e1_outdoor_se_poe_vehicle
//       animal: binary_sensor.e1_outdoor_se_poe_animal
//     - camera: camera.e1_outdoor_se_poe_fluent_2
//       title: E2
//       motion: binary_sensor.e1_outdoor_se_poe_motion_2
;(() => {
  const SENSOR_ICONS = {
    motion: 'mdi:motion-sensor',
    person: 'mdi:account',
    vehicle: 'mdi:car',
    animal: 'mdi:paw',
  }

  function pictureGlanceConfig(hass, camera) {
    const entities = []
    for (const [kind, icon] of Object.entries(SENSOR_ICONS)) {
      const entityId = camera[kind]
      if (entityId && hass.states[entityId]) {
        entities.push({ entity: entityId, icon })
      }
    }

    return {
      type: 'picture-glance',
      entity: camera.camera,
      camera_image: camera.camera,
      camera_view: 'auto',
      title: camera.title,
      tap_action: { action: 'more-info' },
      entities,
    }
  }

  class AnnikaCamerasCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.cameras) || config.cameras.length === 0) {
        throw new Error('annika-cameras-card: "cameras" must be a non-empty list of { camera, title?, motion?, person?, vehicle?, animal? }')
      }
      this._config = config
      this._render()
    }

    set hass(hass) {
      this._hass = hass
      if (this._grid) {
        this._grid.hass = hass
      } else {
        this._render()
      }
    }

    getCardSize() {
      const columns = this._config?.columns || 3
      return Math.ceil((this._config?.cameras?.length || 0) / columns) * 3
    }

    async _render() {
      if (!this._hass || !this._config || this._grid) return

      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement({
        type: 'grid',
        columns: this._config.columns || 3,
        square: false,
        cards: this._config.cameras.map((camera) => pictureGlanceConfig(this._hass, camera)),
      })
      this._grid.hass = this._hass

      this.innerHTML = ''
      if (this._config.title) {
        const header = document.createElement('div')
        header.textContent = this._config.title
        header.style.fontSize = '1.2em'
        header.style.fontWeight = '500'
        header.style.margin = '0 0 8px 4px'
        this.appendChild(header)
      }
      this.appendChild(this._grid)
    }
  }

  customElements.define('annika-cameras-card', AnnikaCamerasCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-cameras-card',
    name: 'Annika Cameras',
    description: 'Lists cameras as picture-glance cards with optional motion/person/vehicle/animal sensors, arranged in a grid.',
  })
})()
