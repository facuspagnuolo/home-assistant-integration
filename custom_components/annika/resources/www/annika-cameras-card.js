// Annika cameras card.
//
// Renders a list of cameras as native picture-glance cards, arranged in a
// grid (3 per row by default). Each camera's motion/person/vehicle/animal
// sensors are all optional — only the ones actually given in config (and
// present in hass.states) are shown; nothing is hardcoded to always appear.
//
// Cameras and their sensors use the shared Annika shape (see
// annika-common.js): either a bare entity id or
// `{ entity, name?, icon?, color? }`. For a camera, `name` is used as the
// card title. The legacy `camera:`/`title:` keys are still accepted.
//
// Usage in a dashboard view:
//   type: custom:annika-cameras-card
//   columns: 3
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//   cameras:
//     - entity: camera.e1_outdoor_se_poe_fluent
//       name: E1
//       motion: binary_sensor.e1_outdoor_se_poe_motion
//       person: binary_sensor.e1_outdoor_se_poe_person
//       vehicle: binary_sensor.e1_outdoor_se_poe_vehicle
//       animal: binary_sensor.e1_outdoor_se_poe_animal
//     - entity: camera.e1_outdoor_se_poe_fluent_2
//       name: E2
//       motion:
//         entity: binary_sensor.e1_outdoor_se_poe_motion_2
//         icon: mdi:run-fast
;(() => {
  const CARD = 'annika-cameras-card'

  const SENSOR_ICONS = {
    motion: 'mdi:motion-sensor',
    person: 'mdi:account',
    vehicle: 'mdi:car',
    animal: 'mdi:paw',
  }

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  // { camera|entity, title|name, motion?, person?, vehicle?, animal? } ->
  // { entity, name?, icon?, color?, sensors: [{ entity, icon, name? }] }
  function normalizeCamera(camera) {
    const { normalizeItem } = annika()

    const raw = typeof camera === 'string' ? { entity: camera } : { ...camera }
    if (raw.entity === undefined && raw.camera !== undefined) raw.entity = raw.camera
    if (raw.name === undefined && raw.title !== undefined) raw.name = raw.title

    const item = normalizeItem(raw, CARD)
    item.sensors = Object.entries(SENSOR_ICONS)
      .filter(([kind]) => raw[kind] !== undefined && raw[kind] !== null)
      .map(([kind, icon]) => ({ icon, ...normalizeItem(raw[kind], CARD) }))

    return item
  }

  function pictureGlanceConfig(hass, camera) {
    return {
      type: 'picture-glance',
      entity: camera.entity,
      camera_image: camera.entity,
      camera_view: 'auto',
      title: camera.name,
      tap_action: { action: 'more-info' },
      entities: camera.sensors.filter((sensor) => hass.states[sensor.entity]),
    }
  }

  class AnnikaCamerasCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.cameras) || config.cameras.length === 0) {
        throw new Error(
          `${CARD}: "cameras" must be a non-empty list of { entity, name?, motion?, person?, vehicle?, animal? }`,
        )
      }
      this._config = config
      this._cameras = config.cameras.map(normalizeCamera)
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
      return Math.ceil((this._cameras?.length || 0) / columns) * 3
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
      if (!this._hass || !this._config || this._grid) return

      const { gridConfig, HEADING_CSS, appendHeading } = annika()
      const helpers = await window.loadCardHelpers()
      this._grid = await helpers.createCardElement(
        gridConfig(
          this._cameras.map((camera) => pictureGlanceConfig(this._hass, camera)),
          this._config.columns || 3,
        ),
      )
      this._grid.hass = this._hass

      this.innerHTML = `<style>${HEADING_CSS}</style>`
      if (this._config.title) {
        this._title = await appendHeading(this, helpers, this._hass, this._config.title, { style: 'title' })
      }
      this.appendChild(this._grid)
    }
  }

    // Declared, not registered: annika-common.js does the registering once its
  // helpers exist. See the queue at the bottom of that file for why.
  ;(window.AnnikaCards ||= []).push(['annika-cameras-card', AnnikaCamerasCard])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-cameras-card',
    name: 'Annika Cameras',
    description: 'Lists cameras as picture-glance cards with optional motion/person/vehicle/animal sensors, arranged in a grid.',
  })
})()
