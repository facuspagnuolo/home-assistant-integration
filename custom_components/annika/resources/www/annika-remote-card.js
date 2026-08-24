// Annika remote card.
//
// A TV remote as a grid of native HA button cards, 6 per row by default.
// Replaces the decluttering-card `tv_remote` template: instead of repeating
// the same 24 button definitions per TV, this card only needs the remote
// entity and builds the whole keypad from it.
//
// Every button sends a `remote.send_command` to the card's remote — power
// included, so no helper script or media_player entity is involved.
//
// The default layout is the Samsung-style KEY_* keypad — d-pad, transport
// and channel keys on the left three columns, numpad on the right three:
//
//   return  power  home   1  2  3
//   vol-    up     vol+   4  5  6
//   left    ok     right  7  8  9
//   pause   down   play   ch- 0  ch+
//
// Usage in a dashboard view:
//   type: custom:annika-remote-card
//   title: Living Room             # optional header above the keypad
//   remote: remote.living_room_tv  # required
//   columns: 6                     # optional, buttons per row
//   grid_options:        # optional, sections view only; card width within
//     columns: 6         # the section's 12-unit grid (12/full = whole row,
//                        # 6 = half, 4 = a third). Defaults to full.
//
// To change the keypad, pass `buttons` — it replaces the default layout
// entirely. Each entry is one of:
//
//   - icon: mdi:home                     # send a remote command
//     command: KEY_HOME
//   - icon: mdi:netflix                  # call any action
//     action: script.open_netflix
//     data:
//       profile: kids
//
//   buttons:
//     - { icon: mdi:power, command: KEY_POWER }
//     - { icon: mdi:home, command: KEY_HOME }
//     - { icon: mdi:netflix, action: script.open_netflix }
;(() => {
  const CARD = 'annika-remote-card'

  const DEFAULT_COLUMNS = 6

  // Read row by row against the default 6 columns.
  const DEFAULT_BUTTONS = [
    { icon: 'mdi:keyboard-return', command: 'KEY_RETURN' },
    { icon: 'mdi:power', command: 'KEY_POWER' },
    { icon: 'mdi:home', command: 'KEY_HOME' },
    { icon: 'mdi:numeric-1', command: 'KEY_1' },
    { icon: 'mdi:numeric-2', command: 'KEY_2' },
    { icon: 'mdi:numeric-3', command: 'KEY_3' },

    { icon: 'mdi:volume-minus', command: 'KEY_VOLDOWN' },
    { icon: 'mdi:chevron-up', command: 'KEY_UP' },
    { icon: 'mdi:volume-plus', command: 'KEY_VOLUP' },
    { icon: 'mdi:numeric-4', command: 'KEY_4' },
    { icon: 'mdi:numeric-5', command: 'KEY_5' },
    { icon: 'mdi:numeric-6', command: 'KEY_6' },

    { icon: 'mdi:chevron-left', command: 'KEY_LEFT' },
    { icon: 'mdi:radiobox-marked', command: 'KEY_ENTER' },
    { icon: 'mdi:chevron-right', command: 'KEY_RIGHT' },
    { icon: 'mdi:numeric-7', command: 'KEY_7' },
    { icon: 'mdi:numeric-8', command: 'KEY_8' },
    { icon: 'mdi:numeric-9', command: 'KEY_9' },

    { icon: 'mdi:pause', command: 'KEY_PAUSE' },
    { icon: 'mdi:chevron-down', command: 'KEY_DOWN' },
    { icon: 'mdi:play', command: 'KEY_PLAY' },
    { icon: 'mdi:chevron-down-box', command: 'KEY_CHDOWN' },
    { icon: 'mdi:numeric-0', command: 'KEY_0' },
    { icon: 'mdi:chevron-up-box', command: 'KEY_CHUP' },
  ]

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  function performAction(action, data, target) {
    const tapAction = { action: 'perform-action', perform_action: action }
    if (target) tapAction.target = target
    if (data) tapAction.data = data
    return tapAction
  }

  function buttonConfig(button, remote) {
    const tapAction = button.action
      ? performAction(button.action, button.data, button.target)
      : performAction('remote.send_command', { command: button.command }, { entity_id: remote })

    // Deliberately the same minimal shape the hand-written decluttering
    // template produced — `name` is only set when asked for, so an icon-only
    // button renders exactly as before.
    const config = { type: 'button', icon: button.icon, tap_action: tapAction }
    if (button.name !== undefined) config.name = button.name
    return config
  }

  class AnnikaRemoteCard extends HTMLElement {
    setConfig(config) {
      if (!config.remote) {
        throw new Error(`${CARD}: "remote" is required`)
      }
      if (config.buttons !== undefined && !Array.isArray(config.buttons)) {
        throw new Error(`${CARD}: "buttons" must be a list of { icon, command } / { icon, action } entries`)
      }

      this._config = config
      this._remote = annika().entityId(config.remote, CARD)
      this._buttons = config.buttons || DEFAULT_BUTTONS

      for (const button of this._buttons) {
        if (!button || typeof button !== 'object') {
          throw new Error(`${CARD}: every button must be an object`)
        }
        if (!button.action && !button.command) {
          throw new Error(`${CARD}: every button needs a "command" or an "action"`)
        }
      }

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
      return Math.ceil(this._buttons.length / (this._config?.columns || DEFAULT_COLUMNS)) * 2
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

      const { gridConfig, createHeader } = annika()
      const helpers = await window.loadCardHelpers()

      this._grid = await helpers.createCardElement({
        ...gridConfig(
          this._buttons.map((button) => buttonConfig(button, this._remote)),
          this._config.columns || DEFAULT_COLUMNS,
        ),
        square: true,
      })
      this._grid.hass = this._hass

      this.innerHTML = ''
      if (this._config.title) {
        this.appendChild(createHeader(this._config.title, '0 0 8px 4px'))
      }
      this.appendChild(this._grid)
    }
  }

  customElements.define('annika-remote-card', AnnikaRemoteCard)

  window.customCards = window.customCards || []
  window.customCards.push({
    type: 'annika-remote-card',
    name: 'Annika Remote',
    description: 'TV remote keypad built from a remote entity, as a grid of native button cards.',
  })
})()
