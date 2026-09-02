// Annika remote card.
//
// A TV remote as a grid of native HA button cards, 6 per row by default.
// Replaces the decluttering-card `tv_remote` template: instead of repeating
// the same 24 button definitions per TV, this card only needs the remote
// entity and builds the whole keypad from it.
//
// Every button sends a `remote.send_command` to the card's remote, with one
// exception: power. A sleeping TV cannot receive a keypress at all, so
// `KEY_POWER` only ever turns one off — which is why power used to look
// broken in one direction.
//
// Give the card the TV's `mac` and the power button calls the
// `tv_power_toggle` script instead: Wake-on-LAN to turn on, the media_player
// to turn off. That is the combination that works whatever Home Assistant
// does with its own turn_on, whose implicit Wake-on-LAN is deprecated and
// removed in 2026.8. It needs the `wake_on_lan` integration enabled and
// Wake-on-LAN switched on in the TV's own settings.
//
// Without a `mac` the button toggles the media_player belonging to the same
// device, found through the device registry (`media_player:` names it
// explicitly). A TV with no media_player at all falls back to KEY_POWER.
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
//   mac: aa:bb:cc:dd:ee:ff         # optional; the TV's MAC, so power can
//                                  # wake it — see above
//   media_player: media_player.living_room_tv   # optional; only needed when
//                                  # it is not on the same device as the
//                                  # remote, or to point power elsewhere
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
    // `power: true` rather than a plain KEY_POWER — see powerAction below.
    { icon: 'mdi:power', command: 'KEY_POWER', power: true },
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

  // The media_player belonging to the same physical device as the remote.
  //
  // Turning a TV *off* is a keypress like any other, but turning one on is
  // not: the TV's network interface is asleep, so nothing sent over the
  // remote's connection reaches it. That is why `remote.send_command
  // KEY_POWER` appears to do nothing when the TV is off, and why pressing
  // power to turn it off works fine — the button is not broken, it can only
  // ever work in one direction.
  //
  // Waking it is Wake-on-LAN, and the entity that knows how to do that is the
  // media_player: `SamsungTVRemote` implements `async_send_command` and
  // `async_turn_off` and nothing else, while `SamsungTVMediaPlayer.async_turn_on`
  // sends the magic packet (or runs the device's configured turn-on trigger).
  // The same split holds for the other TV integrations — the remote sends
  // keys, the media_player owns power.
  //
  // Found through the device registry rather than by guessing at entity ids,
  // so this keeps working whatever the entities are called.
  function powerTarget(hass, remote) {
    const deviceId = hass?.entities?.[remote]?.device_id
    if (!deviceId) return undefined

    for (const [entityId, entry] of Object.entries(hass.entities)) {
      if (entry.device_id === deviceId && entityId.startsWith('media_player.')) {
        return entityId
      }
    }
    return undefined
  }

  // Three ways to power a TV, best first.
  //
  //   mac + a media_player   the tv_power_toggle script: Wake-on-LAN to turn
  //                          on, media_player.turn_off to turn off. The only
  //                          one that reliably works in both directions,
  //                          because it never relies on Home Assistant's own
  //                          turn_on — whose implicit Wake-on-LAN is
  //                          deprecated and removed in 2026.8.
  //   a media_player alone   media_player.toggle. Turning on then depends on
  //                          the integration still doing Wake-on-LAN itself,
  //                          or on the unit having a turn-on trigger set up.
  //   neither                the keypress, which can only ever turn the TV
  //                          off — a sleeping TV receives nothing.
  //
  // `mac` needs a media_player, since that is what the off half acts on; a
  // `mac` with no media_player anywhere falls through to the keypress.
  function powerAction(hass, remote, configured, mac) {
    const target = configured || powerTarget(hass, remote)

    if (target && mac) {
      return performAction('script.tv_power_toggle', { tv: target, mac })
    }
    if (target) {
      return performAction('media_player.toggle', undefined, { entity_id: target })
    }
    return performAction('remote.send_command', { command: 'KEY_POWER' }, { entity_id: remote })
  }

  function buttonConfig(button, remote, hass, mediaPlayer, mac) {
    const tapAction = button.power
      ? powerAction(hass, remote, mediaPlayer, mac)
      : button.action
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
      this._mediaPlayer = config.media_player
        ? annika().entityId(config.media_player, CARD)
        : undefined
      if (config.mac !== undefined && typeof config.mac !== 'string') {
        throw new Error(`${CARD}: "mac" must be the TV's MAC address, e.g. aa:bb:cc:dd:ee:ff`)
      }
      this._mac = config.mac
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
      const previous = this._hass
      this._hass = hass

      // The power button is resolved against the device registry, so a
      // registry change can change where it should point — a media_player
      // appearing after the TV was set up, most often. Rebuilding on the
      // registry's identity costs one reference check per state update.
      if (previous && this._grid && previous.entities !== hass.entities) {
        this._grid = undefined
        this._render()
        return
      }

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

      const { gridConfig, HEADING_CSS, appendHeading } = annika()
      const helpers = await window.loadCardHelpers()

      this._grid = await helpers.createCardElement({
        ...gridConfig(
          this._buttons.map((button) =>
            buttonConfig(button, this._remote, this._hass, this._mediaPlayer, this._mac),
          ),
          this._config.columns || DEFAULT_COLUMNS,
        ),
        square: true,
      })
      this._grid.hass = this._hass

      this.innerHTML = `<style>${HEADING_CSS}</style>`
      if (this._config.title) {
        this._title = await appendHeading(this, helpers, this._hass, this._config.title, { style: 'title' })
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
