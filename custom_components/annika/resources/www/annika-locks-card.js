// Annika locks card: the doors of the house, who opened them, the codes that work on
// them and what happens to the alarm when one is opened (see locks.py).
//
// Usage in a dashboard view:
//   type: custom:annika-locks-card
//   entity: sensor.annika_locks
//   language: es                # optional; by default the Home Assistant language
//
// Each lock is a tile like a camera's: its state where the live view would be, a
// button to open it (press and hold, unless that is turned off in its settings),
// the door and battery chips and a gear. The gear opens the settings of that lock:
// Home Assistant's own tiles, for what the lock's device exposes and for what Annika
// adds (hold to unlock, lock when the door is closed, and after how many seconds).
//
// Beside the doors is the form for a new code, fixed or temporary. Below, over the
// whole width: the codes of every lock (the code shows for a few seconds when the
// eye is pressed, with its emergency variant), the automation that disarms the alarm
// when a door is unlocked, and the activity: who opened and closed what.
//
// Every code has an emergency variant, the same code ending in 0; Annika programs it
// in the lock and, when it is used, opens the door and sends a security notification.
;(() => {
  const CARD = 'annika-locks-card'
  const SERVICE_DOMAIN = 'annika'

  const TEXTS = {
    en: {
      missing: 'Entity not found: {entity}',
      door: 'Door',
      doors: 'Doors',
      codes: 'Codes',
      new_code: 'New code',
      automations: 'Automations',
      activity: 'Activity',
      settings: 'Settings',
      back: 'Back',
      name: 'Name',
      name_hint: 'Who is it for?',
      type: 'Type',
      type_col: 'Type',
      fixed: 'Fixed',
      temporary: 'Temporary',
      code: 'Code',
      generate: 'Generate',
      digits: '4–8 digits',
      err_digits: 'Use 4 to 8 digits',
      err_zero: 'It cannot end in 0: that ending is the emergency alert',
      err_close: 'Too close to another code',
      emergency: 'Emergency',
      emergency_hint: 'same code ending in 0: opens the door and sends a security alert. Every code has one.',
      valid_for: 'Valid for',
      until: 'or until',
      works_on: 'Works on',
      create: 'Create code',
      fixed_hint: 'Stays until you delete it.',
      temp_hint: 'It is removed from the lock by itself when it expires.',
      slot: 'Slot {slot}',
      all: 'All',
      code_one: '{n} code',
      code_other: '{n} codes',
      no_codes: 'No codes for this lock yet.',
      left: '{time} left',
      show: 'Show code',
      hide: 'Hide code',
      copy: 'Copy',
      remove: 'Delete',
      rename: 'Rename',
      rename_prompt: 'New name for this code',
      import_codes: 'Import from locks',
      imported_n: '{n} codes imported. Rename them with the pencil.',
      imported_none: 'No new codes found in the locks.',
      confirm_delete: 'Delete the code “{name}”? It is removed from the lock.',
      error: 'It could not be done',
      rule_title: 'Disarm the alarm when a door is unlocked',
      rule_sub: 'However it was opened: code, fingerprint, key or the app. Also while the alarm is counting down. Only disarms; it never arms.',
      rule_when: 'When',
      rule_alarm: 'Alarm is',
      any_mode: 'Any mode',
      test_quiet: 'Alarm and locks untouched',
      no_alarm: 'The alarm is not set up, so there is nothing to disarm.',
      test: 'Test',
      close_title: 'Lock after closing',
      close_sub: 'Locks itself some seconds after its door closes. Opening the door again cancels it.',
      open_title: 'Notify when left open',
      open_sub: 'Sends a notification if the door stays open longer than that.',
      sec: 'sec',
      needs_sensor: 'Needs a door sensor',
      no_notification: 'Notifications need a notify_view in the configuration.',
      told: 'Notification sent',
      ev_left_open: 'was left open',
      locked: 'Locked',
      unlocked: 'Unlocked',
      unlocking: 'Unlocking…',
      locking: 'Locking…',
      jammed: 'Jammed',
      unavailable: 'Unavailable',
      jammed_detail: 'The bolt is stuck. Check the door.',
      door_open_detail: 'Door open',
      hold_unlock: 'Hold to unlock',
      unlock: 'Unlock',
      lock: 'Lock',
      try_again: 'Try again',
      door_sensor: 'Door sensor',
      door_open: 'Open',
      door_closed: 'Closed',
      battery: 'Battery',
      away: 'Away',
      night: 'Night',
      vacation: 'Vacation',
      home: 'Home',
      someone: 'Someone',
      unknown: 'Unknown',
      unknown_code: 'Unknown code {slot}',
      auto_lock: 'Auto-lock',
      now: 'just now',
      today: 'Today',
      yesterday: 'Yesterday',
      no_activity: 'Nothing has happened yet.',
      no_settings: 'This lock has no settings to show',
      ev_unlock: 'unlocked',
      ev_unlock_keypad: 'unlocked with a code',
      ev_unlock_app: 'unlocked from the app',
      ev_unlock_manual: 'unlocked by hand',
      ev_unlock_remote: 'unlocked remotely',
      ev_lock: 'locked',
      ev_lock_keypad: 'locked from the keypad',
      ev_lock_app: 'locked from the app',
      ev_lock_manual: 'locked by hand',
      ev_lock_auto: 'locked itself',
      ev_lock_close: 'locked itself after the door closed',
      ev_lock_remote: 'locked remotely',
      ev_emergency: 'entered the emergency code',
      ev_unknown: 'a code that is not in the list was used',
      ev_expired: 'temporary code expired and was removed',
      ev_test: 'automation test',
      alarm_disarmed: 'Alarm disarmed',
      security_sent: 'Security notification sent',
    },
    es: {
      missing: 'No se encontró la entidad: {entity}',
      door: 'Puerta',
      doors: 'Puertas',
      codes: 'Códigos',
      new_code: 'Nuevo código',
      automations: 'Automatizaciones',
      activity: 'Actividad',
      settings: 'Ajustes',
      back: 'Volver',
      name: 'Nombre',
      name_hint: '¿Para quién es?',
      type: 'Tipo',
      type_col: 'Tipo',
      fixed: 'Fijo',
      temporary: 'Temporal',
      code: 'Código',
      generate: 'Generar',
      digits: '4 a 8 dígitos',
      err_digits: 'Usá de 4 a 8 dígitos',
      err_zero: 'No puede terminar en 0: ese final es la alerta de emergencia',
      err_close: 'Muy parecido a otro código',
      emergency: 'Emergencia',
      emergency_hint: 'el mismo código terminado en 0: abre la puerta y envía una alerta de seguridad. Todos los códigos lo tienen.',
      valid_for: 'Válido por',
      until: 'o hasta',
      works_on: 'Funciona en',
      create: 'Crear código',
      fixed_hint: 'Queda hasta que lo borres.',
      temp_hint: 'Se borra solo de la cerradura cuando vence.',
      slot: 'Posición {slot}',
      all: 'Todas',
      code_one: '{n} código',
      code_other: '{n} códigos',
      no_codes: 'Todavía no hay códigos para esta cerradura.',
      left: 'Quedan {time}',
      show: 'Mostrar código',
      hide: 'Ocultar código',
      copy: 'Copiar',
      remove: 'Borrar',
      rename: 'Renombrar',
      rename_prompt: 'Nuevo nombre para este código',
      import_codes: 'Importar de las cerraduras',
      imported_n: '{n} códigos importados. Renombralos con el lápiz.',
      imported_none: 'No se encontraron códigos nuevos en las cerraduras.',
      confirm_delete: '¿Borrar el código “{name}”? Se quita de la cerradura.',
      error: 'No se pudo hacer',
      rule_title: 'Desactivar la alarma al abrir una puerta',
      rule_sub: 'Se abra como se abra: código, huella, llave o la app. También mientras la alarma cuenta atrás. Solo desactiva; nunca activa.',
      rule_when: 'Cuando',
      rule_alarm: 'La alarma está',
      any_mode: 'Cualquier modo',
      test_quiet: 'Alarma y cerraduras sin tocar',
      no_alarm: 'La alarma no está configurada, así que no hay nada que desactivar.',
      test: 'Probar',
      close_title: 'Trabar al cerrarse',
      close_sub: 'Se cierra sola unos segundos después de cerrarse la puerta. Si la puerta se vuelve a abrir, se cancela.',
      open_title: 'Avisar si está abierta',
      open_sub: 'Envía una notificación si la puerta sigue abierta más tiempo que ese.',
      sec: 'seg',
      needs_sensor: 'Necesita un sensor de puerta',
      no_notification: 'Las notificaciones necesitan notify_view en la configuración.',
      told: 'Notificación enviada',
      ev_left_open: 'se dejó abierta',
      locked: 'Cerrada',
      unlocked: 'Abierta',
      unlocking: 'Abriendo…',
      locking: 'Cerrando…',
      jammed: 'Trabada',
      unavailable: 'No disponible',
      jammed_detail: 'El pestillo está trabado. Revisá la puerta.',
      door_open_detail: 'Puerta abierta',
      hold_unlock: 'Mantené para abrir',
      unlock: 'Abrir',
      lock: 'Cerrar',
      try_again: 'Reintentar',
      door_sensor: 'Sensor de puerta',
      door_open: 'Abierta',
      door_closed: 'Cerrada',
      battery: 'Batería',
      away: 'Fuera',
      night: 'Noche',
      vacation: 'Vacaciones',
      home: 'En casa',
      someone: 'Alguien',
      unknown: 'Desconocido',
      unknown_code: 'Código desconocido {slot}',
      auto_lock: 'Cierre automático',
      now: 'ahora',
      today: 'Hoy',
      yesterday: 'Ayer',
      no_activity: 'Todavía no pasó nada.',
      no_settings: 'Esta cerradura no tiene ajustes para mostrar',
      ev_unlock: 'abrió',
      ev_unlock_keypad: 'abrió con un código',
      ev_unlock_app: 'abrió desde la app',
      ev_unlock_manual: 'abrió a mano',
      ev_unlock_remote: 'abrió a distancia',
      ev_lock: 'cerró',
      ev_lock_keypad: 'cerró desde el teclado',
      ev_lock_app: 'cerró desde la app',
      ev_lock_manual: 'cerró a mano',
      ev_lock_auto: 'se cerró sola',
      ev_lock_close: 'se cerró sola al cerrarse la puerta',
      ev_lock_remote: 'cerró a distancia',
      ev_emergency: 'ingresó el código de emergencia',
      ev_unknown: 'se usó un código que no está en la lista',
      ev_expired: 'el código temporal venció y se borró',
      ev_test: 'prueba de la automatización',
      alarm_disarmed: 'Alarma desactivada',
      security_sent: 'Notificación de seguridad enviada',
    },
  }

  const HOLD_MS = 1000
  const REVEAL_MS = 8000
  const NOTICE_MS = 6000
  const TICK_MS = 30000
  const HOURS = [1, 2, 6, 24, 72]
  const MODE_ORDER = ['away', 'night', 'vacation']
  const OPEN_KINDS = ['unlock', 'emergency', 'unknown']
  const MOVE_KINDS = ['unlock', 'lock', 'emergency', 'unknown']
  const STATES = { locked: 'locked', unlocked: 'unlocked', open: 'unlocked', opening: 'unlocking', unlocking: 'unlocking', locking: 'locking', jammed: 'jammed' }
  const ICONS = {
    locked: 'mdi:lock', unlocked: 'mdi:lock-open-variant', unlocking: 'mdi:lock-open-variant', locking: 'mdi:lock', jammed: 'mdi:lock-alert', unavailable: 'mdi:lock-question',
  }
  // What the settings of a lock show, in this order; the rest follows.
  const SETTING_DOMAINS = ['switch', 'light', 'select', 'number', 'button', 'update', 'binary_sensor', 'sensor']
  // Entities of the device that are not settings (the lock is the tile).
  const HIDDEN_DOMAINS = ['lock', 'camera', 'image']
  const SETTINGS_COLOR = 'primary'

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')

  // The emergency code of a code: the same one with its last digit changed to 0.
  const emergencyOf = (code) => `${code.slice(0, -1)}0`

  // A code that does not end in 0 (that ending is the emergency alert).
  const randomCode = (length = 6) => {
    const digit = (from, to) => {
      const bytes = new Uint32Array(1)
      if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(bytes)
      else bytes[0] = Math.floor(Math.random() * 4294967296)
      return String(from + (bytes[0] % (to - from + 1)))
    }
    let code = ''
    for (let at = 0; at < length - 1; at += 1) code += digit(0, 9)
    return code + digit(1, 9)
  }

  // A dropdown, drawn like the irrigation card's (see SELECT_CSS in annika-common.js).
  const selectBox = (select) => `<span class="annika-select">${select}</span>`

  const STYLE = `.annika-locks .wide { margin-top: 16px; display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
.annika-locks .sec { font-size: 16px; font-weight: 500; padding: 4px 4px 0; color: var(--primary-text-color); }
.annika-locks .annika-heading { display: block; }
.annika-locks ha-card { display: block; }
.annika-locks ha-card.panel { padding: 12px 16px; box-sizing: border-box; }
.annika-locks ha-card.panel.table { padding: 4px 8px; overflow-x: auto; }
.annika-locks .muted, .annika-locks .sub { color: var(--secondary-text-color); font-size: 13px; }
.annika-locks .notice { color: var(--error-color, #db4437); font-size: 13px; padding: 0 4px; }
.annika-locks .notice:empty { display: none; }
.annika-locks input[type=text], .annika-locks input[type=number], .annika-locks input[type=datetime-local] { background: var(--secondary-background-color, transparent); color: var(--primary-text-color); border: 1px solid var(--divider-color);
  border-radius: 6px; padding: 6px 8px; font: inherit; font-size: 14px; color-scheme: dark light; min-width: 0; }
.annika-locks button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.annika-locks .layout { display: grid; grid-template-columns: minmax(340px, 480px) minmax(0, 1fr); gap: 0 24px; align-items: start; }
.annika-locks .layout > * { min-width: 0; }
.annika-locks .tiles { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.annika-locks ha-card.tile { overflow: hidden; position: relative; }
.annika-locks .status { height: 148px; display: flex; align-items: center; gap: 18px; padding: 0 20px; position: relative; overflow: hidden;
  background: color-mix(in srgb, var(--tone) 7%, #000); transition: background .25s; --tone: var(--primary-color); }
.annika-locks .tile[data-state=unlocked] .status, .annika-locks .tile[data-state=unlocking] .status { --tone: var(--warning-color, #D9954B); }
.annika-locks .tile[data-state=jammed] .status { --tone: var(--error-color, #db4437); }
.annika-locks .tile[data-state=unavailable] .status { --tone: var(--disabled-color); }
.annika-locks .badge { width: 76px; height: 76px; border-radius: 50%; display: grid; place-items: center; flex: none; color: var(--tone);
  background: color-mix(in srgb, var(--tone) 16%, transparent); box-shadow: 0 0 0 1px color-mix(in srgb, var(--tone) 35%, transparent) inset; --mdc-icon-size: 38px; transition: all .25s; }
.annika-locks .tile[data-state=unlocking] .badge, .annika-locks .tile[data-state=locking] .badge { animation: annika-locks-pulse 1.2s ease-in-out infinite; }
@keyframes annika-locks-pulse {0%,100% { box-shadow: 0 0 0 1px color-mix(in srgb, var(--tone) 35%, transparent) inset, 0 0 0 0 color-mix(in srgb, var(--tone) 45%, transparent); } 50% { box-shadow: 0 0 0 1px color-mix(in srgb, var(--tone) 35%, transparent) inset, 0 0 0 10px transparent; }}
@media (prefers-reduced-motion: reduce) {
.annika-locks .tile[data-state=unlocking] .badge, .annika-locks .tile[data-state=locking] .badge { animation: none; }
}
.annika-locks .readout { flex: 1; min-width: 0; }
.annika-locks .readout .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.annika-locks .readout .state { font-size: 22px; font-weight: 500; color: var(--tone); }
.annika-locks .readout .detail { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
.annika-locks .act { position: relative; overflow: hidden; border: 1px solid color-mix(in srgb, var(--tone) 55%, transparent); background: color-mix(in srgb, var(--tone) 14%, transparent); color: var(--tone);
  border-radius: 999px; height: 34px; padding: 0 14px 0 10px; display: inline-flex; align-items: center; gap: 6px; font: inherit; font-weight: 500; font-size: 13px; cursor: pointer; --mdc-icon-size: 18px; flex: none; white-space: nowrap; user-select: none; -webkit-user-select: none; touch-action: none; }
.annika-locks .act .fill { position: absolute; inset: 0; width: 0; background: color-mix(in srgb, var(--tone) 35%, transparent); pointer-events: none; }
.annika-locks .act > * { position: relative; }
.annika-locks .act:disabled { opacity: .55; cursor: default; }
.annika-locks .caption { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; padding: 8px 12px; gap: 8px; }
.annika-locks .caption .name { font-weight: 500; }
.annika-locks .chips { display: inline-flex; align-items: center; gap: 8px; }
.annika-locks .chip { display: inline-flex; align-items: center; gap: 4px; color: var(--disabled-color); font-size: 12px; --mdc-icon-size: 18px; transition: color .2s; }
.annika-locks .chip.on { color: var(--primary-color); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--primary-color) 60%, transparent)); }
.annika-locks .chip.warn { color: var(--warning-color, #D9954B); }
.annika-locks .chip.bad { color: var(--error-color, #db4437); }
.annika-locks .gear { border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; padding: 4px; margin-left: 2px; --mdc-icon-size: 20px; display: inline-flex; border-radius: 50%; }
.annika-locks .gear:hover { color: var(--primary-text-color); }
.annika-locks .pill { --mdc-icon-size: 16px; display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
  border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.annika-locks .pill:hover { border-color: rgba(255,255,255,.2); }
.annika-locks .pill.sel { background: color-mix(in srgb, var(--primary-color) 18%, transparent); border-color: color-mix(in srgb, var(--primary-color) 60%, transparent); color: var(--primary-color); }
.annika-locks .pill.small { font-size: 12px; padding: 3px 10px; }
.annika-locks .pill.back { --mdc-icon-size: 18px; padding: 2px 10px 2px 8px; font-size: 12px; gap: 4px; }
.annika-locks .pill.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
.annika-locks .pill.primary:hover { filter: brightness(1.08); }
.annika-locks .pill:disabled { opacity: .4; cursor: default; }
.annika-locks .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.annika-locks .play { --mdc-icon-size: 20px; width: 36px; height: 36px; border-radius: 50%; border: 0; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex: none;
  background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color); }
.annika-locks .play:active { filter: brightness(.8); }
.annika-locks .iconbtn { --mdc-icon-size: 18px; width: 32px; height: 32px; border-radius: 50%; border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.annika-locks .iconbtn:hover { color: var(--primary-text-color); background: rgba(255,255,255,.06); }
.annika-locks .iconbtn.done { color: var(--primary-color); }
.annika-locks .iconbtn.danger:hover { color: var(--error-color, #db4437); }
.annika-locks table { width: 100%; border-collapse: collapse; }
.annika-locks th { text-align: left; font-weight: 400; font-size: 13px; color: var(--secondary-text-color); padding: 10px 8px; white-space: nowrap; }
.annika-locks td { padding: 8px; border-top: 1px solid var(--divider-color); vertical-align: middle; }
.annika-locks td.act-cell { text-align: right; white-space: nowrap; }
.annika-locks .who { display: flex; align-items: center; gap: 10px; }
.annika-locks .avatar { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; flex: none; font-size: 13px; font-weight: 500; --mdc-icon-size: 17px;
  background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color); }
.annika-locks .avatar.neutral { background: rgba(255,255,255,.07); color: var(--secondary-text-color); }
.annika-locks .avatar.warn { background: color-mix(in srgb, var(--warning-color, #D9954B) 20%, transparent); color: var(--warning-color, #D9954B); }
.annika-locks .avatar.bad { background: color-mix(in srgb, var(--error-color, #db4437) 22%, transparent); color: var(--error-color, #db4437); }
.annika-locks .tag { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 2px 9px; font-size: 12px; --mdc-icon-size: 13px; white-space: nowrap;
  background: rgba(255,255,255,.07); color: var(--secondary-text-color); }
.annika-locks .tag.fixed { background: color-mix(in srgb, var(--primary-color) 16%, transparent); color: var(--primary-color); }
.annika-locks .tag.temp { background: color-mix(in srgb, var(--warning-color, #D9954B) 16%, transparent); color: var(--warning-color, #D9954B); }
.annika-locks .tag.low { background: color-mix(in srgb, var(--error-color, #db4437) 22%, transparent); color: var(--error-color, #db4437); }
.annika-locks .code { font-family: ui-monospace, "SF Mono", Menlo, monospace; letter-spacing: .12em; font-size: 15px; }
.annika-locks .code.hidden { letter-spacing: .25em; color: var(--secondary-text-color); }
.annika-locks .scope { display: inline-flex; gap: 4px; flex-wrap: wrap; }
.annika-locks .emg { color: var(--warning-color, #D9954B); }
.annika-locks .emg .code { font-size: 13px; }
.annika-locks .toolbar-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 8px 4px 4px; }
.annika-locks td.empty { padding: 16px; }
.annika-locks .form { display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: center; }
.annika-locks .form > label { color: var(--secondary-text-color); font-size: 13px; }
.annika-locks .seg { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 999px; padding: 2px; gap: 2px; }
.annika-locks .seg button { border: 0; background: transparent; border-radius: 999px; padding: 5px 14px; font: inherit; font-size: 13px; cursor: pointer; color: var(--secondary-text-color); display: inline-flex; align-items: center; gap: 6px; --mdc-icon-size: 15px; }
.annika-locks .seg button.sel { background: color-mix(in srgb, var(--primary-color) 20%, transparent); color: var(--primary-color); }
.annika-locks .form .actions { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; border-top: 1px solid var(--divider-color); padding-top: 12px; }
.annika-locks .form .bad { color: var(--error-color, #db4437); }
.annika-locks .field { display: inline-flex; align-items: center; gap: 8px; }
.annika-locks input.code { width: 132px; }
.annika-locks ha-card.feed { max-height: 380px; overflow-y: auto; padding: 4px 0; }
.annika-locks .event { display: flex; align-items: center; gap: 12px; padding: 8px 16px; }
.annika-locks .event + .event, .annika-locks .daymark + .event { border-top: 0; }
.annika-locks .event .text { flex: 1; min-width: 0; }
.annika-locks .event .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.annika-locks .event .when { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; text-align: right; --mdc-icon-size: 14px; }
.annika-locks .via { color: var(--secondary-text-color); font-size: 13px; }
.annika-locks .daymark { padding: 8px 16px 2px; font-size: 12px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .06em; }
.annika-locks .daymark:not(:first-child) { border-top: 1px solid var(--divider-color); margin-top: 4px; padding-top: 10px; }
.annika-locks .extra { color: var(--primary-color); }
.annika-locks .extra.bad { color: var(--error-color, #db4437); }
.annika-locks .feed .empty { padding: 16px; }
.annika-locks .rule { display: flex; flex-direction: column; gap: 12px; }
.annika-locks .rule-head { display: flex; align-items: flex-start; gap: 12px; }
.annika-locks .rule-head .grow { flex: 1; min-width: 0; }
.annika-locks .rule-head .title { font-weight: 500; }
.annika-locks .rule-body { display: grid; grid-template-columns: 110px 1fr; gap: 10px 12px; align-items: center; padding-left: 34px; }
.annika-locks .rule-body > .k { color: var(--secondary-text-color); font-size: 13px; }
.annika-locks .rule.off .rule-body { opacity: .4; pointer-events: none; }
.annika-locks .settings-head { display: flex; align-items: center; gap: 12px; }
.annika-locks .settings-head .sec { padding-top: 0; flex: 1; min-width: 0; }
.annika-locks .annika-tile-row { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); column-gap: var(--ha-section-column-gap, 8px); row-gap: var(--ha-section-row-gap, 8px); }
.annika-locks .annika-tile-row > * { min-width: 0; }
.annika-locks .annika-tile-row .settings-tiles { display: contents; }
.annika-locks .annika-tile-row > .live-tile { grid-column: span 2; grid-row: span 4; align-self: start; }
.annika-locks .empty-note { padding: 4px; }
@container (max-width: 1100px) {
.annika-locks .annika-tile-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.annika-locks .annika-tile-row > .live-tile { grid-column: auto; grid-row: span 3; }
}
@container (max-width: 800px) {
.annika-locks .layout { grid-template-columns: minmax(0, 1fr); }
.annika-locks .annika-tile-row { grid-template-columns: minmax(0, 1fr); }
.annika-locks .annika-tile-row > .live-tile { grid-column: auto; grid-row: auto; }
.annika-locks .form, .annika-locks .rule-body { grid-template-columns: minmax(0, 1fr); }
.annika-locks .rule-body { padding-left: 0; }
.annika-locks .status { height: auto; padding: 16px; gap: 14px; min-height: 110px; }
.annika-locks .badge { width: 60px; height: 60px; --mdc-icon-size: 30px; }
.annika-locks .who .avatar { display: none; }
.annika-locks .iconbtn { width: 28px; }
.annika-locks .settings-table td.device { width: 30%; }
.annika-locks .settings-table input[type=number] { width: 56px; }
.annika-locks td.act-cell { padding-right: 0; }
.annika-locks .hide-s { display: none; }
.annika-locks .event { padding: 8px 12px; }
.annika-locks td, .annika-locks th { padding: 8px 4px; }
}
.annika-locks input[type=number] { width: 72px; }
.annika-locks .settings-table th { white-space: nowrap; }
.annika-locks .settings-table td.device { width: 40%; }
.annika-locks .settings-table .cell { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.annika-locks .settings-table .cell.off { opacity: .45; }
.annika-locks .note { padding: 0 4px; }
`

  class AnnikaLocksCard extends HTMLElement {
    setConfig(config) {
      if (!config.entity) throw new Error(`${CARD}: "entity" is required`)
      this._config = config
      this._structure = ''
      // The lock whose settings are open (replaces the card's content), or null.
      this._settings = null
      this._tiles = {}
      this._filter = 'all'
      this._revealed = {}
      this._timers = {}
      this._form = { name: '', type: 'fixed', code: randomCode(), hours: 24, until: '', locks: null, error: '', busy: false }
      this._formKey = ''
      this._notice = ''
      this._render()
    }

    connectedCallback() {
      this._structure = ''
      this._tick = setInterval(() => this._updateTimes(), TICK_MS)
      if (this._config && this._hass) this._render()
    }

    disconnectedCallback() {
      clearInterval(this._tick)
      this._tick = null
      Object.values(this._timers || {}).forEach((timer) => clearTimeout(timer))
      this._timers = {}
    }

    set hass(hass) {
      this._hass = hass
      this._render()
      this._updateTimes()
      if (this._settings) Object.values(this._tiles).forEach((el) => (el.hass = hass))
    }

    getCardSize() {
      return 10
    }

    // Full width: a narrow column would switch the card to its mobile layout.
    getGridOptions() {
      return { columns: 'full' }
    }

    getLayoutOptions() {
      return { grid_columns: 'full' }
    }

    get _lang() {
      const lang = (window.Annika && window.Annika.language)
        ? window.Annika.language(this._hass, this._config)
        : (this._config.language || (this._hass && this._hass.language) || 'en')
      return String(lang).toLowerCase().split('-')[0]
    }

    get _texts() {
      return { ...TEXTS.en, ...(TEXTS[this._lang] || {}) }
    }

    get _stateObj() {
      return this._hass && this._hass.states[this._config.entity]
    }

    _service(service, data) {
      return this._hass.callService(SERVICE_DOMAIN, service, { entity_id: this._config.entity, ...data })
    }

    _icon(name) {
      return `<ha-icon icon="${name}"></ha-icon>`
    }

    // --- what the doors are doing ----------------------------------------------

    _stateOf(entityId) {
      return this._hass && this._hass.states[entityId]
    }

    _lockById(config, id) {
      return config.locks.find((lock) => lock.id === id)
    }

    // The state of a lock, its door and battery, and who last moved it.
    _lockInfo(config, lock, events) {
      const state = this._stateOf(lock.entity)
      const door = lock.sensor && this._stateOf(lock.sensor)
      const battery = lock.battery && this._stateOf(lock.battery)
      const level = battery ? parseFloat(battery.state) : NaN
      const since = state && state.last_changed ? state.last_changed : null
      // Who: the last thing logged for this lock, when it is what the state is showing.
      const last = (events || []).find((event) => event.lock === lock.id && MOVE_KINDS.includes(event.kind))
      let who = null
      if (last && since && Math.abs(Date.parse(last.time) - Date.parse(since)) <= 60000) who = this._who(last, this._texts)
      return {
        state: (state && STATES[state.state]) || 'unavailable',
        door: door && (door.state === 'on' ? 'open' : door.state === 'off' ? 'closed' : null),
        battery: Number.isFinite(level) ? Math.round(level) : null,
        since,
        who,
      }
    }

    _who(event, t) {
      if (event.kind === 'unknown') return event.slot ? fill(t.unknown_code, { slot: event.slot }) : t.unknown
      if (event.who) return event.who
      if (event.how === 'auto') return t.auto_lock
      if (event.how === 'close') return 'Annika'
      return t.someone
    }

    // --- time -------------------------------------------------------------------

    _ago(iso) {
      const t = this._texts
      const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000)
      if (!(minutes >= 1)) return t.now
      let format
      try {
        format = new Intl.RelativeTimeFormat(this._lang, { numeric: 'always', style: 'short' })
      } catch (err) {
        format = null
      }
      const hours = Math.floor(minutes / 60)
      const days = Math.floor(hours / 24)
      const [value, unit] = minutes < 60 ? [minutes, 'minute'] : hours < 24 ? [hours, 'hour'] : [days, 'day']
      return format ? format.format(-value, unit) : `${value} ${unit[0]}`
    }

    _left(iso) {
      const minutes = Math.max(0, Math.round((Date.parse(iso) - Date.now()) / 60000))
      if (minutes < 60) return `${minutes} min`
      const hours = Math.floor(minutes / 60)
      if (hours >= 48) return `${Math.floor(hours / 24)} d`
      return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`
    }

    _clock(iso) {
      return new Date(iso).toLocaleTimeString(this._lang, { hour: 'numeric', minute: '2-digit' })
    }

    _day(iso) {
      const t = this._texts
      const date = new Date(iso)
      const now = new Date()
      if (date.toDateString() === now.toDateString()) return t.today
      const yesterday = new Date(now)
      yesterday.setDate(now.getDate() - 1)
      if (date.toDateString() === yesterday.toDateString()) return t.yesterday
      return date.toLocaleDateString(this._lang, { month: 'short', day: 'numeric' })
    }

    // The relative times change without the card being drawn again.
    _updateTimes() {
      if (!this.querySelectorAll) return
      this.querySelectorAll('[data-since]').forEach((el) => {
        el.textContent = this._ago(el.dataset.since)
      })
      const t = this._texts
      this.querySelectorAll('[data-until]').forEach((el) => {
        el.textContent = fill(t.left, { time: this._left(el.dataset.until) })
      })
    }

    // --- the doors --------------------------------------------------------------

    _doorsHtml(config, t) {
      const tiles = config.locks.map((lock) => this._tileHtml(config, lock, t, true)).join('')
      const heading = config.locks.length > 1 ? t.doors : t.door
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(heading)}">${escapeHtml(heading)}</div><div class="tiles">${tiles}</div></div>`
    }

    _tileHtml(config, lock, t, gear) {
      const id = escapeHtml(lock.id)
      const info = this._lockInfo(config, lock, this._events)
      const busy = info.state === 'unlocking' || info.state === 'locking'
      let detail = ''
      if (info.state === 'jammed') detail = escapeHtml(t.jammed_detail)
      else if (info.door === 'open') detail = escapeHtml(t.door_open_detail)
      else if (info.since && info.state !== 'unavailable') {
        detail = `${info.who ? `${escapeHtml(info.who)} · ` : ''}<span data-since="${escapeHtml(info.since)}">${escapeHtml(this._ago(info.since))}</span>`
      }
      let button = ''
      if (info.state === 'jammed') {
        button = `<button class="act" data-lock="${id}">${this._icon('mdi:refresh')}<span>${escapeHtml(t.try_again)}</span></button>`
      } else if (info.state === 'unlocked' || info.state === 'unlocking') {
        button = `<button class="act" data-lock="${id}"${busy ? ' disabled' : ''}>${this._icon('mdi:lock')}<span>${escapeHtml(t.lock)}</span></button>`
      } else if (info.state !== 'unavailable') {
        const hold = lock.settings.hold
        button = `<button class="act" data-unlock="${id}" data-hold="${hold ? 1 : 0}"${busy ? ' disabled' : ''}><span class="fill"></span>${this._icon('mdi:lock-open-variant')}<span>${escapeHtml(hold ? t.hold_unlock : t.unlock)}</span></button>`
      }
      const chips = []
      if (info.door) {
        chips.push(`<span class="chip ${info.door === 'open' ? 'warn' : 'on'}" title="${escapeHtml(t.door_sensor)}">${this._icon(info.door === 'open' ? 'mdi:door-open' : 'mdi:door-closed')}${escapeHtml(info.door === 'open' ? t.door_open : t.door_closed)}</span>`)
      }
      if (info.battery !== null) {
        chips.push(`<span class="chip${info.battery < 20 ? ' bad' : ''}" title="${escapeHtml(t.battery)}">${this._icon(info.battery < 20 ? 'mdi:battery-alert' : 'mdi:battery')}${info.battery}%</span>`)
      }
      const cog = gear
        ? `<button class="gear" data-settings="${id}" title="${escapeHtml(t.settings)}" aria-label="${escapeHtml(t.settings)}">${this._icon('mdi:cog')}</button>`
        : ''
      return `<ha-card class="tile" data-state="${info.state}">
        <div class="status">
          <div class="badge">${this._icon(ICONS[info.state])}</div>
          <div class="readout"><div class="top"><div class="state">${escapeHtml(t[info.state])}</div>${button}</div><div class="detail">${detail}</div></div>
        </div>
        <div class="caption"><span class="name">${escapeHtml(lock.name)}</span><span class="chips">${chips.join('')}${cog}</span></div>
      </ha-card>`
    }

    // --- the new code form ------------------------------------------------------

    _selectedLocks(config) {
      return this._form.locks || config.locks.map((lock) => lock.id)
    }

    _codeError(config, code) {
      const t = this._texts
      if (!/^\d{4,8}$/.test(code)) return t.err_digits
      if (code.endsWith('0')) return t.err_zero
      const codes = (this._stateObj && this._stateObj.attributes.codes) || []
      if (codes.some((other) => other.code === code || emergencyOf(other.code) === code || emergencyOf(code) === other.code || emergencyOf(other.code) === emergencyOf(code))) return t.err_close
      return ''
    }

    _canCreate(config) {
      const form = this._form
      if (form.busy || !form.name.trim() || this._selectedLocks(config).length === 0) return false
      if (this._codeError(config, form.code)) return false
      return form.type !== 'temporary' || !!form.until || form.hours > 0
    }

    _formHtml(config, t) {
      const form = this._form
      const error = this._codeError(config, form.code)
      const selected = this._selectedLocks(config)
      const valid = /^\d{4,8}$/.test(form.code) && !form.code.endsWith('0')
      const hours = form.type === 'temporary'
        ? `<label>${escapeHtml(t.valid_for)}</label><div class="row">
            ${HOURS.map((h) => `<button class="pill small${!form.until && form.hours === h ? ' sel' : ''}" data-fhours="${h}">${h < 24 ? `${h} h` : `${h / 24} d`}</button>`).join('')}
            <span class="muted">${escapeHtml(t.until)}</span><input type="datetime-local" data-f="until" value="${escapeHtml(form.until)}" style="width:190px"></div>`
        : ''
      const locks = config.locks.length > 1
        ? `<label>${escapeHtml(t.works_on)}</label><div class="row">${config.locks.map((lock) =>
          `<label class="field"><input type="checkbox" class="annika-check" data-flock="${escapeHtml(lock.id)}"${selected.includes(lock.id) ? ' checked' : ''}><span>${escapeHtml(lock.name)}</span></label>`).join('')}</div>`
        : ''
      return `<div class="sec" data-heading="${escapeHtml(t.new_code)}">${escapeHtml(t.new_code)}</div>
        <ha-card class="panel"><div class="form">
          <label>${escapeHtml(t.name)}</label><input type="text" data-f="name" placeholder="${escapeHtml(t.name_hint)}" value="${escapeHtml(form.name)}">
          <label>${escapeHtml(t.type)}</label><div><div class="seg">
            <button data-ftype="fixed" class="${form.type === 'fixed' ? 'sel' : ''}">${this._icon('mdi:infinity')}${escapeHtml(t.fixed)}</button>
            <button data-ftype="temporary" class="${form.type === 'temporary' ? 'sel' : ''}">${this._icon('mdi:timer-outline')}${escapeHtml(t.temporary)}</button></div></div>
          <label>${escapeHtml(t.code)}</label><div class="row"><input type="text" class="code" data-f="code" value="${escapeHtml(form.code)}" maxlength="8" inputmode="numeric" autocomplete="off">
            <button class="pill small" data-regen>${this._icon('mdi:refresh')}${escapeHtml(t.generate)}</button>
            <span class="muted${error ? ' bad' : ''}" data-codehint>${escapeHtml(error || t.digits)}</span></div>
          <label>${escapeHtml(t.emergency)}</label><div class="row"><span class="code emg" data-emg>${valid ? escapeHtml(emergencyOf(form.code)) : '—'}</span><span class="muted">${escapeHtml(t.emergency_hint)}</span></div>
          ${hours}${locks}
          <div class="actions"><span class="muted${form.error ? ' bad' : ''}" data-formhint>${escapeHtml(form.error || (form.type === 'temporary' ? t.temp_hint : t.fixed_hint))}</span>
            <button class="pill primary" data-create${this._canCreate(config) ? '' : ' disabled'}>${escapeHtml(t.create)}</button></div>
        </div></ha-card>`
    }

    // The form lives in an element of its own that survives the card being drawn
    // again, so what is being typed is not lost when a door changes state.
    _formElement() {
      if (!this._formEl) this._formEl = document.createElement('div')
      return this._formEl
    }

    _drawForm(config) {
      const element = this._formElement()
      element.className = 'wide'
      element.innerHTML = this._formHtml(config, this._texts)
      this._bindForm(config, element)
      this._headings(element)
    }

    _formChanged(config) {
      const hint = this._formEl.querySelector('[data-codehint]')
      const emergency = this._formEl.querySelector('[data-emg]')
      const create = this._formEl.querySelector('[data-create]')
      const t = this._texts
      const error = this._codeError(config, this._form.code)
      const valid = /^\d{4,8}$/.test(this._form.code) && !this._form.code.endsWith('0')
      if (hint) {
        hint.textContent = error || t.digits
        hint.classList.toggle('bad', !!error)
      }
      if (emergency) emergency.textContent = valid ? emergencyOf(this._form.code) : '—'
      if (create) create.disabled = !this._canCreate(config)
    }

    _bindForm(config, root) {
      const on = (selector, event, handler) => root.querySelectorAll(selector).forEach((el) => el.addEventListener(event, (e) => handler(el, e)))
      const form = this._form
      on('[data-f]', 'input', (el) => {
        form[el.dataset.f] = el.value
        form.error = ''
        this._formChanged(config)
      })
      on('[data-ftype]', 'click', (el) => {
        form.type = el.dataset.ftype
        this._drawForm(config)
      })
      on('[data-fhours]', 'click', (el) => {
        form.hours = Number(el.dataset.fhours)
        form.until = ''
        this._drawForm(config)
      })
      on('[data-regen]', 'click', () => {
        form.code = randomCode()
        form.error = ''
        this._drawForm(config)
      })
      on('[data-flock]', 'change', (el) => {
        const id = el.dataset.flock
        const now = this._selectedLocks(config)
        form.locks = el.checked ? [...now, id] : now.filter((other) => other !== id)
        this._formChanged(config)
      })
      on('[data-create]', 'click', () => this._create(config))
    }

    async _create(config) {
      const form = this._form
      if (!this._canCreate(config)) return
      const entities = this._selectedLocks(config).map((id) => this._lockById(config, id)).filter(Boolean).map((lock) => lock.entity)
      const data = { name: form.name.trim(), type: form.type, code: form.code, locks: entities }
      if (form.type === 'temporary') {
        if (form.until) data.until = form.until
        else data.hours = form.hours
      }
      form.busy = true
      form.error = ''
      this._drawForm(config)
      try {
        await this._service('add_lock_code', data)
        this._form = { name: '', type: form.type, code: randomCode(), hours: form.hours, until: '', locks: null, error: '', busy: false }
      } catch (err) {
        form.busy = false
        form.error = (err && err.message) || this._texts.error
      }
      this._drawForm(config)
    }

    // --- the codes --------------------------------------------------------------

    _codesHtml(config, codes, t) {
      const visible = codes.filter((code) => this._filter === 'all' || code.locks.includes(this._filter))
      const filters = config.locks.length > 1
        ? [['all', t.all], ...config.locks.map((lock) => [lock.id, lock.name])].map(([id, label]) =>
          `<button class="pill small${this._filter === id ? ' sel' : ''}" data-filter="${escapeHtml(id)}">${escapeHtml(label)}</button>`).join('')
        : ''
      const rows = visible.map((code) => {
        const temporary = code.type === 'temporary'
        const low = temporary && code.expires && Date.parse(code.expires) - Date.now() < 30 * 60000
        const type = temporary
          ? `<span class="tag ${low ? 'low' : 'temp'}">${this._icon('mdi:timer-outline')}<span data-until="${escapeHtml(code.expires || '')}">${escapeHtml(fill(t.left, { time: code.expires ? this._left(code.expires) : '' }))}</span></span>`
          : `<span class="tag fixed">${this._icon('mdi:infinity')}${escapeHtml(t.fixed)}</span>`
        const shown = !!this._revealed[code.id]
        const id = escapeHtml(code.id)
        const scope = code.locks.map((lockId) => {
          const lock = this._lockById(config, lockId)
          return lock ? `<span class="tag">${escapeHtml(lock.name)}</span>` : ''
        }).join('')
        return `<tr>
          <td><div class="who"><span class="avatar${temporary ? ' warn' : ''}">${this._icon(temporary ? 'mdi:timer-outline' : 'mdi:key')}</span><div><div>${escapeHtml(code.name)}</div><div class="sub">${escapeHtml(fill(t.slot, { slot: code.slot }))}</div></div></div></td>
          <td>${type}</td>
          <td class="hide-s"><span class="scope">${scope}</span></td>
          <td><span class="code${shown ? '' : ' hidden'}">${shown ? escapeHtml(code.code) : '••••••'}</span>${shown ? `<div class="sub emg">${escapeHtml(t.emergency)} <span class="code">${escapeHtml(emergencyOf(code.code))}</span></div>` : ''}</td>
          <td class="act-cell">
            <button class="iconbtn" data-reveal="${id}" title="${escapeHtml(shown ? t.hide : t.show)}" aria-label="${escapeHtml(shown ? t.hide : t.show)}">${this._icon(shown ? 'mdi:eye-off' : 'mdi:eye')}</button>
            <button class="iconbtn hide-s" data-copy="${id}" title="${escapeHtml(t.copy)}" aria-label="${escapeHtml(t.copy)}">${this._icon('mdi:content-copy')}</button>
            <button class="iconbtn hide-s" data-rename="${id}" title="${escapeHtml(t.rename)}" aria-label="${escapeHtml(t.rename)}">${this._icon('mdi:pencil')}</button>
            <button class="iconbtn danger" data-del="${id}" title="${escapeHtml(t.remove)}" aria-label="${escapeHtml(t.remove)}">${this._icon('mdi:delete')}</button>
          </td></tr>`
      }).join('') || `<tr><td colspan="5" class="muted empty">${escapeHtml(t.no_codes)}</td></tr>`
      const count = fill(visible.length === 1 ? t.code_one : t.code_other, { n: visible.length })
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.codes)}">${escapeHtml(t.codes)}</div>
        <ha-card class="panel table">
          <div class="toolbar-row"><span class="row">${filters}</span><span class="row"><span class="muted">${escapeHtml(count)}</span><button class="pill small" data-import>${this._icon('mdi:download')}${escapeHtml(t.import_codes)}</button></span></div>
          <table><thead><tr><th>${escapeHtml(t.name)}</th><th>${escapeHtml(t.type_col)}</th><th class="hide-s">${escapeHtml(t.works_on)}</th><th>${escapeHtml(t.code)}</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table>
        </ha-card><div class="notice" data-notice>${escapeHtml(this._notice)}</div></div>`
    }

    _reveal(id) {
      clearTimeout(this._timers[id])
      if (this._revealed[id]) {
        delete this._revealed[id]
      } else {
        this._revealed[id] = true
        this._timers[id] = setTimeout(() => {
          delete this._revealed[id]
          this._render()
        }, REVEAL_MS)
      }
      this._render()
    }

    _say(message) {
      this._notice = message || ''
      this.querySelectorAll('[data-notice]').forEach((el) => {
        el.textContent = this._notice
      })
      clearTimeout(this._timers.notice)
      if (message) {
        this._timers.notice = setTimeout(() => {
          this._notice = ''
          this._say('')
        }, NOTICE_MS)
      }
    }

    async _rename(id) {
      const code = ((this._stateObj && this._stateObj.attributes.codes) || []).find((item) => item.id === id)
      if (!code || typeof prompt !== 'function') return
      const t = this._texts
      const name = prompt(t.rename_prompt, code.name)
      if (name === null || !String(name).trim() || String(name).trim() === code.name) return
      try {
        await this._service('rename_lock_code', { id, name: String(name).trim() })
        this._say('')
      } catch (err) {
        this._say((err && err.message) || t.error)
      }
    }

    async _import() {
      const t = this._texts
      const before = ((this._stateObj && this._stateObj.attributes.codes) || []).length
      try {
        await this._service('import_lock_codes', {})
        const after = ((this._stateObj && this._stateObj.attributes.codes) || []).length
        this._say(after > before ? fill(t.imported_n, { n: after - before }) : t.imported_none)
      } catch (err) {
        this._say((err && err.message) || t.error)
      }
    }

    async _delete(config, id) {
      const code = ((this._stateObj && this._stateObj.attributes.codes) || []).find((item) => item.id === id)
      if (!code) return
      const t = this._texts
      if (typeof confirm === 'function' && !confirm(fill(t.confirm_delete, { name: code.name }))) return
      try {
        await this._service('delete_lock_code', { id })
        this._say('')
      } catch (err) {
        this._say((err && err.message) || t.error)
      }
    }

    // --- automations ------------------------------------------------------------

    _modeLabel(mode, t) {
      return t[mode] || mode
    }

    _automationsHtml(config, t) {
      const rule = config.rule
      const selected = rule.locks.length ? rule.locks : config.locks.map((lock) => lock.id)
      const lockPills = config.locks.length > 1
        ? config.locks.map((lock) => `<button class="pill small${selected.includes(lock.id) ? ' sel' : ''}" data-rlock="${escapeHtml(lock.id)}">${escapeHtml(lock.name)}</button>`).join('')
        : `<button class="pill small sel" disabled>${escapeHtml(config.locks[0] ? config.locks[0].name : '')}</button>`
      const modes = [...config.modes].sort((a, b) => MODE_ORDER.indexOf(a) - MODE_ORDER.indexOf(b))
      const modePills = `<button class="pill small${rule.modes.length ? '' : ' sel'}" data-rany>${escapeHtml(t.any_mode)}</button>` +
        modes.map((mode) => `<button class="pill small${rule.modes.includes(mode) ? ' sel' : ''}" data-rmode="${escapeHtml(mode)}">${escapeHtml(this._modeLabel(mode, t))}</button>`).join('')
      const notes = rule.available ? '' : `<div class="muted">${escapeHtml(t.no_alarm)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.automations)}">${escapeHtml(t.automations)}</div>
        <ha-card class="panel"><div class="rule${rule.enabled ? '' : ' off'}">
          <div class="rule-head">
            <input type="checkbox" class="annika-check" data-ron${rule.enabled ? ' checked' : ''}${rule.available ? '' : ' disabled'} style="margin-top:2px">
            <div class="grow"><div class="title">${escapeHtml(t.rule_title)}</div><div class="sub">${escapeHtml(t.rule_sub)}</div></div>
            <button class="play" data-rtest title="${escapeHtml(t.test)}" aria-label="${escapeHtml(t.test)}">${this._icon('mdi:play')}</button>
          </div>
          <div class="rule-body">
            <span class="k">${escapeHtml(t.rule_when)}</span><span class="row">${lockPills}</span>
            <span class="k">${escapeHtml(t.rule_alarm)}</span><span class="row">${modePills}</span>
          </div>
          ${notes}
        </div></ha-card></div>`
    }

    // The settings of the doors in one table: a column per lock, a row per setting, each cell a
    // switch and a number of seconds. They are entities of Annika's (the ones Home Assistant
    // shows and automates too).
    _settingsTableHtml(config, t) {
      const rows = [
        { kind: 'close', seconds: 'seconds', secondsEntity: 'seconds', min: 5, max: 600, step: 5 },
        { kind: 'open', seconds: 'open_seconds', secondsEntity: 'open_seconds', min: 10, max: 3600, step: 10 },
      ].map((row) => {
        const cells = config.locks.map((lock) => {
          const switchEntity = lock.entities[row.kind]
          const numberEntity = lock.entities[row.secondsEntity]
          const usable = !!lock.sensor && !!switchEntity && !!numberEntity
          return `<td><div class="cell${usable ? '' : ' off'}"${usable ? '' : ` title="${escapeHtml(t.needs_sensor)}"`}>
            <input type="checkbox" class="annika-check" data-lswitch="${escapeHtml(switchEntity || '')}"${lock.settings[row.kind] ? ' checked' : ''}${usable ? '' : ' disabled'} aria-label="${escapeHtml(`${t[`${row.kind}_title`]} · ${lock.name}`)}">
            <input type="number" data-lnumber="${escapeHtml(numberEntity || '')}" min="${row.min}" max="${row.max}" step="${row.step}" value="${escapeHtml(lock.settings[row.seconds])}"${usable ? '' : ' disabled'}>
            <span class="muted">${escapeHtml(t.sec)}</span></div></td>`
        }).join('')
        return `<tr><td class="device"><div>${escapeHtml(t[`${row.kind}_title`])}</div><div class="sub hide-s">${escapeHtml(t[`${row.kind}_sub`])}</div></td>${cells}</tr>`
      }).join('')
      const note = config.notification ? '' : `<div class="muted note">${escapeHtml(t.no_notification)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.settings)}">${escapeHtml(t.settings)}</div>
        <ha-card class="panel table"><table class="settings-table">
          <thead><tr><th></th>${config.locks.map((lock) => `<th>${escapeHtml(lock.name)}</th>`).join('')}</tr></thead>
          <tbody>${rows}</tbody></table></ha-card>${note}</div>`
    }

    // The locks of the rule are sent as entities: an empty list is every lock.
    _setLocks(config, id) {
      const rule = config.rule
      const now = rule.locks.length ? rule.locks : config.locks.map((lock) => lock.id)
      const next = now.includes(id) ? now.filter((other) => other !== id) : [...now, id]
      if (next.length === 0) return
      const every = next.length === config.locks.length
      const entities = next.map((lockId) => this._lockById(config, lockId)).filter(Boolean).map((lock) => lock.entity)
      this._service('set_lock_rule', { locks: every ? [] : entities })
    }

    _setModes(config, mode) {
      const modes = config.rule.modes
      this._service('set_lock_rule', { modes: modes.includes(mode) ? modes.filter((other) => other !== mode) : [...modes, mode] })
    }

    // --- activity ---------------------------------------------------------------

    _eventView(config, event, t) {
      const lock = this._lockById(config, event.lock)
      const how = event.how
      const kind = event.kind
      const who = this._who(event, t)
      let text = t[`ev_${kind}_${how}`] || t[`ev_${kind}`] || ''
      let avatar
      let extra = ''
      let bad = false
      const person = event.who && (how === 'keypad' || how === 'app')
      if (kind === 'emergency') {
        avatar = `<span class="avatar bad">${this._icon('mdi:alert')}</span>`
        if (event.notified) {
          extra = t.security_sent
          bad = true
        }
      } else if (kind === 'unknown') {
        avatar = `<span class="avatar bad">${this._icon('mdi:help')}</span>`
      } else if (kind === 'left_open') {
        avatar = `<span class="avatar warn">${this._icon('mdi:door-open')}</span>`
        if (event.notified) extra = t.told
      } else if (kind === 'expired') {
        avatar = `<span class="avatar warn">${this._icon('mdi:timer-off-outline')}</span>`
      } else if (kind === 'test') {
        avatar = `<span class="avatar neutral">${this._icon('mdi:play-circle-outline')}</span>`
      } else if (person) {
        avatar = `<span class="avatar">${escapeHtml(Array.from(event.who)[0] || '?')}</span>`
      } else {
        const icon = { app: 'mdi:cellphone', keypad: 'mdi:dialpad', manual: 'mdi:hand-back-right', auto: 'mdi:lock-clock', close: 'mdi:lock-clock' }[how] || 'mdi:account'
        avatar = `<span class="avatar neutral">${this._icon(icon)}</span>`
      }
      if (event.disarmed) extra = t.alarm_disarmed
      if (kind === 'test') {
        text = t.ev_test
        extra = t.test_quiet
      }
      const subject = kind === 'test' ? 'Annika' : kind === 'left_open' ? (lock ? lock.name : '') : who
      return {
        avatar,
        who: subject,
        text,
        lock: lock && kind !== 'left_open' ? lock.name : '',
        extra,
        bad,
        open: OPEN_KINDS.includes(kind),
        icon: kind === 'expired' || kind === 'test' || kind === 'left_open' ? '' : OPEN_KINDS.includes(kind) ? 'mdi:lock-open-variant' : 'mdi:lock',
      }
    }

    _activityHtml(config, events, t) {
      let day = ''
      const rows = events.map((event) => {
        const label = this._day(event.time)
        const mark = label !== day ? `<div class="daymark">${escapeHtml(label)}</div>` : ''
        day = label
        const view = this._eventView(config, event, t)
        const sub = [view.lock ? escapeHtml(view.lock) : '', view.extra ? `<span class="extra${view.bad ? ' bad' : ''}">${escapeHtml(view.extra)}</span>` : ''].filter(Boolean).join(' · ')
        return `${mark}<div class="event">${view.avatar}
          <div class="text"><div class="line"><b>${escapeHtml(view.who)}</b><span class="via">${escapeHtml(view.text)}</span></div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>
          <div class="when">${escapeHtml(this._clock(event.time))}${view.icon ? `<div>${this._icon(view.icon)}</div>` : ''}</div></div>`
      }).join('') || `<div class="muted empty">${escapeHtml(t.no_activity)}</div>`
      return `<div class="wide"><div class="sec" data-heading="${escapeHtml(t.activity)}">${escapeHtml(t.activity)}</div><ha-card class="feed">${rows}</ha-card></div>`
    }

    // --- settings of one lock ---------------------------------------------------
    //
    // Home Assistant's own tile card per entity, with the one feature its kind of
    // entity calls for, in a grid, the lock beside them: what Annika adds to the
    // lock, then what the lock's device exposes, then its door and battery.

    // The words an entity name starts with that only repeat what the lock is called.
    _ownName(id, lock) {
      const state = this._hass.states[id]
      const name = (state.attributes && state.attributes.friendly_name) || id
      return name.length > lock.name.length + 1 && name.startsWith(`${lock.name} `) ? name.slice(lock.name.length + 1) : name
    }

    _settingEntities(lock) {
      const registry = (this._hass && this._hass.entities) || {}
      const states = (this._hass && this._hass.states) || {}
      // What is Annika's and also a setting of the door (the rest is in the Automations).
      const own = [lock.entities && lock.entities.hold].filter((id) => id && states[id])
      const device = registry[lock.entity] && registry[lock.entity].device_id
      const rank = (id) => {
        const at = SETTING_DOMAINS.indexOf(id.split('.')[0])
        return at < 0 ? SETTING_DOMAINS.length : at
      }
      const fromDevice = device
        ? Object.keys(registry)
          .filter((id) => registry[id].device_id === device && !registry[id].hidden && !registry[id].hidden_by && states[id])
          .filter((id) => id !== lock.entity && !HIDDEN_DOMAINS.includes(id.split('.')[0]) && !own.includes(id))
          .sort((a, b) => rank(a) - rank(b) || this._deviceName(a, device).localeCompare(this._deviceName(b, device)))
        : []
      const known = new Set([...own, ...fromDevice])
      const extra = [lock.sensor, lock.battery].filter((id) => id && states[id] && !known.has(id))
      return [...own, ...fromDevice, ...extra]
    }

    _deviceName(id, device) {
      const state = this._hass.states[id]
      const name = (state.attributes && state.attributes.friendly_name) || id
      const registered = this._hass.devices && this._hass.devices[device]
      const prefix = registered && (registered.name_by_user || registered.name)
      return prefix && name.length > prefix.length + 1 && name.startsWith(`${prefix} `) ? name.slice(prefix.length + 1) : name
    }

    _settingName(id, lock) {
      const t = this._texts
      if (id === lock.sensor) return t.door_sensor
      if (id === lock.battery) return t.battery
      const device = this._hass.entities && this._hass.entities[id] && this._hass.entities[id].device_id
      const own = !!lock.entities && lock.entities.hold === id
      return own || !device ? this._ownName(id, lock) : this._deviceName(id, device)
    }

    // The tile config for one entity (annika-common's tileConfig, as the other cards use it).
    _settingTile(id, lock) {
      const domain = id.split('.')[0]
      const attrs = (this._hass.states[id] && this._hass.states[id].attributes) || {}
      let features = []
      // A switch or a light has no feature: tapping its tile turns it on and off.
      if (domain === 'select') features = [{ type: 'select-options' }]
      else if (domain === 'number') features = [{ type: 'numeric-input', style: attrs.mode === 'box' ? 'buttons' : 'slider' }]
      return window.Annika.tileConfig({ entity: id, name: this._settingName(id, lock), color: SETTINGS_COLOR }, { features })
    }

    _settingsHtml(config, t) {
      const lock = this._lockById(config, this._settings)
      if (!lock) return ''
      const empty = this._settingEntities(lock).length === 0
      return `<div class="wide">
        <div class="settings-head">
          <button class="pill back" data-back title="${escapeHtml(t.back)}">${this._icon('mdi:arrow-left')}${escapeHtml(t.back)}</button>
          <div class="sec" data-heading="${escapeHtml(`${lock.name} · ${t.settings}`)}">${escapeHtml(lock.name)} · ${escapeHtml(t.settings)}</div>
        </div>
        <div class="annika-tile-row settings">
          <div class="live-tile">${this._tileHtml(config, lock, t, false)}</div>
          <span class="settings-tiles" data-settings-tiles></span>
        </div>
        ${empty ? `<div class="muted empty-note">${escapeHtml(t.no_settings)}</div>` : ''}
      </div>`
    }

    // The tiles are Home Assistant's own cards, built once per entity and put back
    // into place after every render.
    async _mountSettings(config) {
      const lock = this._lockById(config, this._settings)
      if (!lock || !window.loadCardHelpers) return
      try {
        const helpers = await window.loadCardHelpers()
        const elements = []
        for (const id of this._settingEntities(lock)) {
          if (!this._tiles[id]) {
            const element = await helpers.createCardElement(this._settingTile(id, lock))
            element.hass = this._hass
            this._tiles[id] = element
          }
          elements.push(this._tiles[id])
        }
        // Went back while these were being built: nothing to put them in.
        const target = this._settings === lock.id && this.querySelector('[data-settings-tiles]')
        if (target) target.replaceChildren(...elements)
      } catch (err) {
        // The lock's own tile stays.
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

    // --- rendering --------------------------------------------------------------

    _render(force) {
      if (!this._config) return
      const stateObj = this._stateObj
      const t = this._texts
      if (!stateObj) {
        this._bodyElement().innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(fill(t.missing, { entity: this._config.entity }))}</div></ha-card>`
        this._structure = ''
        return
      }
      const config = stateObj.attributes.config
      if (!config) return
      const codes = stateObj.attributes.codes || []
      const events = stateObj.attributes.events || []
      this._events = events
      // A lock that is no longer in the configuration has no settings to show.
      if (this._settings && !config.locks.some((lock) => lock.id === this._settings)) this._settings = null
      const infos = config.locks.map((lock) => this._lockInfo(config, lock, events))
      const lockEntity = this._settings && this._lockById(config, this._settings)
      const key = JSON.stringify([
        config, codes, events, infos, this._filter, this._revealed, t.doors, t.codes,
        this._settings, lockEntity ? this._settingEntities(lockEntity) : '',
      ])
      if (!force && key === this._structure) return
      this._structure = key

      // Keep the height while the content is rebuilt (the titles arrive a moment later):
      // on a phone a shorter page would scroll itself back to the top.
      const keep = this.offsetHeight
      if (keep) this.style.minHeight = `${keep}px`
      this._bodyElement().innerHTML = `
        <style>
          annika-locks-card { display: block; container-type: inline-size; }
          .annika-locks { display: block; }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}
          ${(window.Annika && window.Annika.SELECT_CSS) || ''}
          ${STYLE}
        </style>
        <div class="annika-locks">
          ${this._settings
            ? this._settingsHtml(config, t)
            : `<div class="layout"><div>${this._doorsHtml(config, t)}</div><div data-form-host></div></div>
               ${this._codesHtml(config, codes, t)}${this._settingsTableHtml(config, t)}${this._automationsHtml(config, t)}${this._activityHtml(config, events, t)}`}
        </div>
      `
      this._bind(config)
      const host = this.querySelector('[data-form-host]')
      if (host) {
        const formKey = JSON.stringify([config.locks.map((lock) => [lock.id, lock.name]), t.new_code])
        if (formKey !== this._formKey || !this._formEl) {
          this._formKey = formKey
          this._drawForm(config)
        }
        host.replaceChildren(this._formElement())
        this._formChanged(config)
      }
      if (this._settings) this._mountSettings(config)
      this._headings(this)
      this._headings(this.querySelector('.annika-locks')).then(() => requestAnimationFrame(() => { this.style.minHeight = '' }))
    }

    // Section titles are Home Assistant's own heading card, like the other
    // Annika cards; the plain text stays until it is ready.
    async _headings(root) {
      if (!root || !window.loadCardHelpers || !window.Annika) return
      try {
        const helpers = await window.loadCardHelpers()
        for (const host of root.querySelectorAll('[data-heading]')) {
          if (host.firstElementChild && host.firstElementChild.classList.contains('annika-heading')) continue
          const card = await helpers.createCardElement(window.Annika.headingConfig(host.dataset.heading, { style: 'title' }))
          card.hass = this._hass
          card.classList.add('annika-heading')
          if (host.isConnected) host.replaceChildren(card)
        }
      } catch (err) {
        // The plain title stays.
      }
    }

    // --- opening and closing ----------------------------------------------------

    _lockEntity(id) {
      const stateObj = this._stateObj
      const lock = stateObj && stateObj.attributes.config.locks.find((item) => item.id === id)
      return lock && lock.entity
    }

    _open(id) {
      const entity = this._lockEntity(id)
      if (entity) this._hass.callService('lock', 'unlock', { entity_id: entity })
    }

    _close(id) {
      const entity = this._lockEntity(id)
      if (entity) this._hass.callService('lock', 'lock', { entity_id: entity })
    }

    // Unlocking is press and hold, so a tap in a pocket does not open the door; the
    // button fills while it is held and the door opens when it is full.
    _bindHold(el) {
      const id = el.dataset.unlock
      if (el.dataset.hold !== '1') {
        el.addEventListener('click', () => this._open(id))
        return
      }
      const fillEl = el.querySelector('.fill')
      let frame = null
      let started = null
      const stop = () => {
        if (frame !== null && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame)
        frame = null
        started = null
        if (fillEl) fillEl.style.width = '0'
      }
      const step = (now) => {
        if (started === null) started = now
        const progress = Math.min(1, (now - started) / HOLD_MS)
        if (fillEl) fillEl.style.width = `${progress * 100}%`
        if (progress >= 1) {
          stop()
          this._open(id)
        } else {
          frame = requestAnimationFrame(step)
        }
      }
      const begin = () => {
        if (frame === null) frame = requestAnimationFrame(step)
      }
      el.addEventListener('pointerdown', (event) => {
        if (el.setPointerCapture && event.pointerId !== undefined) {
          try {
            el.setPointerCapture(event.pointerId)
          } catch (err) {
            // Not capturable: leaving the button cancels the hold instead.
          }
        }
        begin()
      })
      ;['pointerup', 'pointercancel', 'pointerleave', 'blur'].forEach((name) => el.addEventListener(name, stop))
      el.addEventListener('keydown', (event) => {
        if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) {
          event.preventDefault()
          begin()
        }
      })
      el.addEventListener('keyup', stop)
      el.addEventListener('contextmenu', (event) => event.preventDefault())
    }

    // --- events -----------------------------------------------------------------

    _bind(config) {
      const on = (selector, event, handler) =>
        this.querySelectorAll(selector).forEach((el) => el.addEventListener(event, (e) => handler(el, e)))

      on('[data-settings]', 'click', (el) => this._openSettings(el.dataset.settings))
      on('[data-back]', 'click', () => this._closeSettings())
      on('[data-lock]', 'click', (el) => this._close(el.dataset.lock))
      this.querySelectorAll('[data-unlock]').forEach((el) => this._bindHold(el))

      on('[data-filter]', 'click', (el) => {
        this._filter = el.dataset.filter
        this._render(true)
      })
      on('[data-reveal]', 'click', (el) => this._reveal(el.dataset.reveal))
      on('[data-copy]', 'click', (el) => {
        const code = ((this._stateObj && this._stateObj.attributes.codes) || []).find((item) => item.id === el.dataset.copy)
        if (!code || typeof navigator === 'undefined' || !navigator.clipboard) return
        navigator.clipboard.writeText(code.code).then(() => {
          el.classList.add('done')
          setTimeout(() => el.classList.remove('done'), 1500)
        }, () => {})
      })
      on('[data-rename]', 'click', (el) => this._rename(el.dataset.rename))
      on('[data-import]', 'click', () => this._import())
      on('[data-del]', 'click', (el) => this._delete(config, el.dataset.del))

      on('[data-ron]', 'change', (el) => this._service('set_lock_rule', { enabled: el.checked }))
      on('[data-rlock]', 'click', (el) => this._setLocks(config, el.dataset.rlock))
      on('[data-rany]', 'click', () => this._service('set_lock_rule', { modes: [] }))
      on('[data-rmode]', 'click', (el) => this._setModes(config, el.dataset.rmode))
      on('[data-rtest]', 'click', () => this._service('test_lock_rule', {}))
      on('[data-lswitch]', 'change', (el) => {
        if (el.dataset.lswitch) this._hass.callService('switch', el.checked ? 'turn_on' : 'turn_off', { entity_id: el.dataset.lswitch })
      })
      on('[data-lnumber]', 'change', (el) => {
        if (el.dataset.lnumber && el.value !== '') this._hass.callService('number', 'set_value', { entity_id: el.dataset.lnumber, value: Number(el.value) })
      })
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaLocksCard])
})()
