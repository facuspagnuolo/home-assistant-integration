// Annika heating card: the thermostats of the house by zone, what they are set to and
// why, how the day goes by schedule and the heating season (see heating.py).
//
// Usage in a dashboard view:
//   type: custom:annika-heating-card
//   entity: sensor.annika_heating
//   language: es                # optional; by default the Home Assistant language
//
// On top, the general switch (off: everything is turned off and left alone; on: every
// thermostat is back in Auto) and the boilers, which follow the demand by themselves.
// Each zone is a card like the cameras': its target with a – and a +, why it is that
// (the slot of the schedule, or a manual one) and what comes next, the temperature of
// the day as a chart (the zone as a whole, or each room) and a tile per thermostat with
// its own – and +, its settings behind the gear and an Auto pill when somebody set it by
// hand: a manual target stays until it is put back to Auto.
//
// Below, over the whole width: the schedule of a zone for workdays and for the rest of
// the days (a slot may apply to some rooms only, and only when there has been no motion
// for some time; until that is met the slot before it stays), the heating season and the
// activity.
//
// A dashboard that lists `entities:` instead of an `entity:` still gets the thermostat
// tiles of annika-ac-tiles-card, as before.
;(() => {
  const CARD = 'annika-heating-card'
  const SERVICE_DOMAIN = 'annika'
  const STEP = 0.5
  const MIN_TARGET = 5
  const MAX_TARGET = 35
  const DEFAULT_TARGET = 20
  const HISTORY_MS = 5 * 60 * 1000
  const BUCKET_MS = 10 * 60 * 1000
  const TICK_MS = 30000
  const PALETTE = [
    'var(--primary-color, #33C46E)', 'var(--warning-color, #D9954B)', '#8fd6a8', '#c9774a',
    '#5fa87c', '#e6c08a', '#2e8f55', '#a6502b',
  ]
  const SETTING_DOMAINS = ['switch', 'light', 'select', 'number', 'button', 'update', 'binary_sensor', 'sensor']
  const HIDDEN_DOMAINS = ['climate', 'camera', 'image']
  const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

  const TEXTS = {
    en: {
      missing: 'Entity not found: {entity}',
      heating: 'Heating',
      boiler: 'Boiler',
      on: 'On',
      off: 'Off',
      standby: 'Out of season',
      season_on: 'On · heating season ({temp})',
      season_off: 'On · out of season ({temp})',
      season_any: 'On',
      master_off: 'Off · nothing is automated',
      running: 'Running',
      boiler_idle: 'Idle',
      of_heating: '{n} of {total} thermostats heating',
      lower: 'Lower',
      raise: 'Raise',
      now_avg: 'Now {temp} average · {n} of {total} heating',
      now_one: 'Now {temp} · {state}',
      not_heating: 'not heating',
      heating_now: 'heating',
      since: '{target} since {time}',
      next: 'Next: {name} at {time} · {target}',
      next_if: 'Next: {name} at {time} · {target} if no motion for {minutes}',
      manual_line: 'Set by hand, until you press Auto',
      manual_mixed: 'Some thermostats are set by hand',
      season_line: 'Out of season: the thermostats on Auto are off',
      none_line: 'No slot of the schedule applies: off',
      empty_line: 'Set a target to turn it on, or add it to a schedule',
      tomorrow: 'tomorrow {time}',
      auto: 'Auto',
      manual_n: '{n} manual',
      mixed: 'mixed',
      zone: 'Zone',
      rooms: 'Rooms',
      temperature: 'Temperature',
      target: 'Target',
      planned: 'Planned',
      heating_status: 'Heating',
      idle: 'Idle',
      settings: 'Settings',
      back: 'Back',
      no_settings: 'This thermostat has no settings to show',
      schedule: 'Schedule',
      workday: 'Workday',
      weekday: 'Mon–Fri',
      weekend: 'Sat–Sun',
      non_workday: 'Non-workday',
      today_is: 'Today is a {day}',
      today_is_day: 'Today is {day}',
      starts_at: 'Starts at',
      name: 'Name',
      only_if: 'Only if',
      applies_to: 'Applies to',
      all_rooms: 'All rooms',
      rooms_n: '{n} rooms',
      add_slot: 'Add slot',
      add_condition: 'Add a condition',
      no_condition: 'Always',
      remove_condition: 'Remove the condition',
      delete: 'Delete',
      slot_name: 'Name',
      slot_hint: 'Until its condition is met, the previous slot stays in effect.',
      no_motion_in: 'no motion in',
      for: 'for',
      min: 'min',
      motion_sensors: 'Motion sensors',
      motion_sensors_n: '{n} motion sensors',
      choose_sensors: 'Choose sensors',
      motion_hint: 'The slot applies when all the selected sensors have been off for the time you set.',
      rooms_hint: 'The slot applies to the selected rooms. None selected: all of them.',
      no_slots: 'No slots: the thermostats of this zone stay off.',
      automations: 'Automations',
      season: 'Heating season',
      season_below: 'Turn heating on when the forecast stays below',
      season_above: 'Turn heating off when the forecast stays above',
      season_for: 'for',
      hours: 'h',
      season_now: 'Now: {state} · forecast {temp}',
      season_in: 'in season',
      season_out: 'out of season',
      no_weather: 'No weather entity is configured: the heating is always in season.',
      activity: 'Activity',
      no_activity: 'Nothing has happened yet.',
      yesterday: 'Yesterday {time}',
      ev_slot: '{zone} → {target} · {name}',
      ev_manual: '{who} set to {target} · manual until Auto',
      ev_manual_external: '{who} set to {target} on the thermostat · manual until Auto',
      ev_manual_off: '{who} turned off · manual until Auto',
      ev_auto: '{who} back to Auto',
      ev_boiler_on: '{boiler} on',
      ev_boiler_off: '{boiler} off',
      ev_boiler_who: '{who} started heating',
      ev_season_on: 'Heating season started ({temp})',
      ev_season_off: 'Heating season ended ({temp})',
      ev_master_on: 'Heating switched on · everything back to Auto',
      ev_master_off: 'Heating switched off · thermostats and boilers turned off',
      error: 'It could not be done',
    },
    es: {
      missing: 'No se encontró la entidad: {entity}',
      heating: 'Calefacción',
      boiler: 'Caldera',
      on: 'Encendida',
      off: 'Apagada',
      standby: 'Fuera de temporada',
      season_on: 'Encendida · temporada de calefacción ({temp})',
      season_off: 'Encendida · fuera de temporada ({temp})',
      season_any: 'Encendida',
      master_off: 'Apagada · nada se automatiza',
      running: 'Funcionando',
      boiler_idle: 'En reposo',
      of_heating: '{n} de {total} termostatos calentando',
      lower: 'Bajar',
      raise: 'Subir',
      now_avg: 'Ahora {temp} de promedio · {n} de {total} calentando',
      now_one: 'Ahora {temp} · {state}',
      not_heating: 'sin calentar',
      heating_now: 'calentando',
      since: '{target} desde las {time}',
      next: 'Sigue: {name} a las {time} · {target}',
      next_if: 'Sigue: {name} a las {time} · {target} si no hay movimiento por {minutes}',
      manual_line: 'Ajustada a mano, hasta que pulses Auto',
      manual_mixed: 'Algunos termostatos están ajustados a mano',
      season_line: 'Fuera de temporada: los termostatos en Auto están apagados',
      none_line: 'Ningún tramo del horario aplica: apagada',
      empty_line: 'Poné una temperatura para encenderla, o agregala a un horario',
      tomorrow: 'mañana {time}',
      auto: 'Auto',
      manual_n: '{n} manual',
      mixed: 'mixto',
      zone: 'Zona',
      rooms: 'Ambientes',
      temperature: 'Temperatura',
      target: 'Objetivo',
      planned: 'Previsto',
      heating_status: 'Calentando',
      idle: 'En reposo',
      settings: 'Ajustes',
      back: 'Volver',
      no_settings: 'Este termostato no tiene ajustes para mostrar',
      schedule: 'Horario',
      workday: 'Día laborable',
      weekday: 'Lun–Vie',
      weekend: 'Sáb–Dom',
      non_workday: 'Día no laborable',
      today_is: 'Hoy es un día {day}',
      today_is_day: 'Hoy es {day}',
      starts_at: 'Empieza a las',
      name: 'Nombre',
      only_if: 'Solo si',
      applies_to: 'Aplica a',
      all_rooms: 'Todos los ambientes',
      rooms_n: '{n} ambientes',
      add_slot: 'Agregar tramo',
      add_condition: 'Agregar condición',
      no_condition: 'Siempre',
      remove_condition: 'Quitar la condición',
      delete: 'Borrar',
      slot_name: 'Nombre',
      slot_hint: 'Hasta que se cumpla su condición, sigue vigente el tramo anterior.',
      no_motion_in: 'sin movimiento en',
      for: 'por',
      min: 'min',
      motion_sensors: 'Sensores de movimiento',
      motion_sensors_n: '{n} sensores de movimiento',
      choose_sensors: 'Elegir sensores',
      motion_hint: 'El tramo aplica cuando todos los sensores elegidos llevan apagados el tiempo que indiques.',
      rooms_hint: 'El tramo aplica a los ambientes elegidos. Ninguno: todos.',
      no_slots: 'Sin tramos: los termostatos de esta zona quedan apagados.',
      automations: 'Automatizaciones',
      season: 'Temporada de calefacción',
      season_below: 'Encender la calefacción cuando el pronóstico se mantenga por debajo de',
      season_above: 'Apagar la calefacción cuando el pronóstico se mantenga por encima de',
      season_for: 'durante',
      hours: 'h',
      season_now: 'Ahora: {state} · pronóstico {temp}',
      season_in: 'en temporada',
      season_out: 'fuera de temporada',
      no_weather: 'No hay una entidad de clima configurada: la calefacción siempre está en temporada.',
      activity: 'Actividad',
      no_activity: 'Todavía no pasó nada.',
      yesterday: 'Ayer {time}',
      ev_slot: '{zone} → {target} · {name}',
      ev_manual: '{who} a {target} · manual hasta Auto',
      ev_manual_external: '{who} a {target} en el termostato · manual hasta Auto',
      ev_manual_off: '{who} apagado · manual hasta Auto',
      ev_auto: '{who} vuelve a Auto',
      ev_boiler_on: '{boiler} encendida',
      ev_boiler_off: '{boiler} apagada',
      ev_boiler_who: '{who} empezó a calentar',
      ev_season_on: 'Empezó la temporada de calefacción ({temp})',
      ev_season_off: 'Terminó la temporada de calefacción ({temp})',
      ev_master_on: 'Calefacción encendida · todo vuelve a Auto',
      ev_master_off: 'Calefacción apagada · termostatos y calderas apagados',
      error: 'No se pudo hacer',
    },
  }

  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')
  const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)
  const deg = (value) => `${Number(value).toFixed(1)}°`
  const clamp = (value) => Math.max(MIN_TARGET, Math.min(MAX_TARGET, value))
  const selectBox = (select) => `<span class="annika-select">${select}</span>`
  const minutesOf = (clock) => {
    const [h, m] = String(clock).split(':').map(Number)
    return h * 60 + m
  }

  // The rules are written on one line each: they are all scoped to the card here.
  const scope = (css) =>
    css
      .split('\n')
      .map((line) =>
        /^[.a-z[*]/i.test(line) && line.includes('{')
          ? line.replace(/^([^{]+)\{/, (_, selector) => `${selector.split(',').map((one) => `.annika-heating ${one.trim()}`).join(', ')} {`)
          : line,
      )
      .join('\n')

  const STYLE = scope(`.wide { margin-top: 16px; display: flex; flex-direction: column; gap: var(--ha-section-row-gap, 8px); }
.sec { font-size: 16px; font-weight: 500; padding: 4px 4px 0; display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--primary-text-color); }
.annika-heading { display: block; }
ha-card { display: block; }
ha-card.panel { padding: 12px 16px; box-sizing: border-box; }
ha-card.panel.table { padding: 4px 8px; overflow-x: auto; }
.muted, .sub { color: var(--secondary-text-color); font-size: 13px; }
.notice { color: var(--error-color, #db4437); font-size: 13px; padding: 0 4px; }
.notice:empty { display: none; }
input[type=text], input[type=number], input[type=time] { background: var(--secondary-background-color, transparent); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 6px; padding: 6px 8px; font: inherit; font-size: 14px; color-scheme: dark light; min-width: 0; }
input[type=number] { width: 64px; }
input[type=time] { width: 124px; }
button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.u { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.stile { display: flex; align-items: center; gap: 12px; padding: 12px 14px; --tone: var(--primary-color); }
.master-host { display: contents; }
.stile.click { cursor: pointer; }
.stile .ico { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex: none; color: var(--tone); background: color-mix(in srgb, var(--tone) 16%, transparent); --mdc-icon-size: 22px; }
.stile .txt { flex: 1; min-width: 0; }
.stile .t { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stile .s { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stile.heat { --tone: var(--warning-color, #D9954B); }
.stile.idle, .stile.off { --tone: var(--disabled-color); }
.stile.heat .ico { animation: annika-heating-pulse 2s ease-in-out infinite; }
@keyframes annika-heating-pulse { 0%,100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--tone) 40%, transparent); } 50% { box-shadow: 0 0 0 8px transparent; } }
@media (prefers-reduced-motion: reduce) { .annika-heating .stile.heat .ico { animation: none; } }
.zones { margin-top: 16px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: start; }
.zone { padding: 0; overflow: hidden; --tone: var(--warning-color, #D9954B); }
.zone.full { grid-column: 1 / -1; }
.zone-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px 0; }
.zone-head .name { font-size: 16px; font-weight: 500; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.zone-head .right { display: flex; align-items: center; gap: 8px; }
.zone-main { display: flex; align-items: center; gap: 18px; padding: 12px 16px 4px; flex-wrap: wrap; }
.dial { display: flex; align-items: center; gap: 10px; flex: none; }
.bigtemp { font-size: 44px; font-weight: 500; line-height: 1; color: var(--tone); min-width: 112px; text-align: center; letter-spacing: -1px; }
.bigtemp small { font-size: 18px; font-weight: 400; opacity: .8; letter-spacing: 0; }
.bigtemp.off { color: var(--disabled-color); }
.round { --mdc-icon-size: 22px; width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--divider-color); background: rgba(255,255,255,.04); color: var(--primary-text-color); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.round:hover { border-color: rgba(255,255,255,.22); }
.why { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 6px; }
.why .line { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--secondary-text-color); --mdc-icon-size: 16px; }
.why .line b { color: var(--primary-text-color); font-weight: 500; }
.why .now { font-size: 13px; color: var(--secondary-text-color); }
.why .now b { color: var(--primary-text-color); font-weight: 500; }
.chart { padding: 6px 12px 0; }
.chart svg { width: 100%; height: auto; display: block; }
.chart-wrap { position: relative; }
.chart-toggle { display: flex; justify-content: flex-end; gap: 6px; padding: 8px 16px 0; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; padding: 0 16px 8px; font-size: 12px; color: var(--secondary-text-color); }
.legend i { display: inline-block; width: 14px; height: 3px; margin-right: 6px; vertical-align: middle; border-radius: 2px; }
.tag { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 2px 9px; font-size: 12px; --mdc-icon-size: 13px; white-space: nowrap; background: rgba(255,255,255,.07); color: var(--secondary-text-color); font-weight: 400; }
.tag.manual { background: color-mix(in srgb, var(--warning-color, #D9954B) 18%, transparent); color: var(--warning-color, #D9954B); }
.rooms { display: flex; flex-wrap: wrap; gap: 1px; background: var(--divider-color); border-top: 1px solid var(--divider-color); }
.room { flex: 1 1 calc(100% / var(--cols, 4) - 1px); min-width: 168px; background: var(--ha-card-background, var(--card-background-color)); padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; --tone: var(--disabled-color); box-sizing: border-box; }
.room.heating { --tone: var(--warning-color, #D9954B); }
.room .top { display: flex; align-items: center; gap: 6px; }
.room .badge { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; flex: none; --mdc-icon-size: 17px; color: var(--tone); background: color-mix(in srgb, var(--tone) 18%, transparent); }
.room .nm { flex: 1; min-width: 0; font-weight: 500; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gear { border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; padding: 2px; display: inline-flex; border-radius: 50%; --mdc-icon-size: 18px; }
.room .mid { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.room .cur { font-size: 20px; font-weight: 500; letter-spacing: -.3px; }
.room.off .cur { color: var(--secondary-text-color); }
.step, .stepper { display: inline-flex; flex: none; align-items: center; gap: 2px; background: rgba(255,255,255,.05); padding: 2px; border-radius: 10px; }
.step button, .stepper button { --mdc-icon-size: 16px; width: 28px; height: 28px; border-radius: 8px; border: 0; background: transparent; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; color: var(--secondary-text-color); padding: 0; }
.step button:hover, .stepper button:hover { background: rgba(255,255,255,.07); color: var(--primary-text-color); }
.step .v { font-size: 13px; min-width: 40px; text-align: center; }
.stepper .v { min-width: 52px; text-align: center; font-weight: 500; }
.room.override .step { outline: 1px solid color-mix(in srgb, var(--warning-color, #D9954B) 55%, transparent); }
.room.override .step .v { color: var(--warning-color, #D9954B); font-weight: 500; }
.room .foot { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 11px; color: var(--secondary-text-color); min-height: 22px; --mdc-icon-size: 13px; }
.room .foot .f { display: inline-flex; align-items: center; gap: 3px; color: var(--warning-color, #D9954B); }
.pill { --mdc-icon-size: 16px; display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.pill.sel { background: color-mix(in srgb, var(--primary-color) 18%, transparent); border-color: color-mix(in srgb, var(--primary-color) 60%, transparent); color: var(--primary-color); }
.pill.small { font-size: 12px; padding: 3px 10px; }
.pill.warn { border-color: color-mix(in srgb, var(--warning-color, #D9954B) 60%, transparent); color: var(--warning-color, #D9954B); background: color-mix(in srgb, var(--warning-color, #D9954B) 12%, transparent); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.iconbtn { --mdc-icon-size: 18px; width: 32px; height: 32px; border-radius: 50%; border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.toolbar-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.bar { position: relative; height: 34px; display: flex; overflow: hidden; background: #000; margin: 4px 0 0; }
.bar .seg { height: 100%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 500; color: rgba(0,0,0,.78); overflow: hidden; white-space: nowrap; }
.bar .seg.cond { background-image: repeating-linear-gradient(135deg, rgba(0,0,0,.28) 0 5px, transparent 5px 10px); color: rgba(255,255,255,.85); }
.bar .seg.none { background: rgba(255,255,255,.06); color: var(--secondary-text-color); }
.bar .nowline { position: absolute; top: 0; bottom: 0; width: 2px; background: #fff; box-shadow: 0 0 6px rgba(255,255,255,.7); }
.ticks { display: flex; justify-content: space-between; font-size: 11px; color: var(--disabled-color); padding-top: 3px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-weight: 400; font-size: 13px; color: var(--secondary-text-color); padding: 10px 8px; white-space: nowrap; }
td { padding: 8px; border-top: 1px solid var(--divider-color); vertical-align: middle; }
td.act-cell { text-align: right; white-space: nowrap; }
.cond { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; color: var(--secondary-text-color); font-size: 13px; --mdc-icon-size: 16px; }
.cond .iconbtn { width: 24px; height: 24px; --mdc-icon-size: 14px; }
.dd { position: relative; display: inline-flex; align-items: center; max-width: 100%; height: 34px; padding: 0 32px 0 12px; border: 0; border-radius: 12px; background: color-mix(in srgb, var(--disabled-color) 20%, transparent); color: var(--primary-text-color); font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.dd.empty { color: var(--secondary-text-color); }
.dd::after { content: ''; position: absolute; top: 50%; right: 6px; width: 24px; height: 24px; margin-top: -12px; pointer-events: none; background: var(--secondary-text-color); -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7,10L12,15L17,10H7Z'/%3E%3C/svg%3E") center / contain no-repeat; mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7,10L12,15L17,10H7Z'/%3E%3C/svg%3E") center / contain no-repeat; }
.popover { position: absolute; z-index: 10; width: 320px; max-width: calc(100vw - 24px); max-height: 60vh; overflow: auto; background: var(--card-background-color, #121415); border: 1px solid rgba(255,255,255,.12); box-shadow: 0 12px 32px rgba(0,0,0,.6); padding: 12px 14px; box-sizing: border-box; }
.pop-title { font-weight: 500; }
.pop-sub { color: var(--secondary-text-color); font-size: 12px; margin: 2px 0 8px; }
.pop-row { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px solid var(--divider-color); cursor: pointer; }
.pop-row .muted { margin-left: auto; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule { display: flex; align-items: flex-start; gap: 14px; padding: 12px 4px; }
.rule .avatar { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; flex: none; --mdc-icon-size: 18px; background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color); }
.rule.off .avatar { background: rgba(255,255,255,.07); color: var(--secondary-text-color); }
.rule .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.rule .title { font-weight: 500; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rule .params { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--secondary-text-color); font-size: 13px; }
.rule.off .params { opacity: .5; }
.events { display: flex; flex-direction: column; }
.event { display: flex; align-items: center; gap: 12px; padding: 9px 4px; border-top: 1px solid var(--divider-color); }
.event:first-child { border-top: 0; }
.event .avatar { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; flex: none; --mdc-icon-size: 16px; background: rgba(255,255,255,.07); color: var(--secondary-text-color); }
.event .avatar.heat { background: color-mix(in srgb, var(--warning-color, #D9954B) 18%, transparent); color: var(--warning-color, #D9954B); }
.event .avatar.ok { background: color-mix(in srgb, var(--primary-color) 20%, transparent); color: var(--primary-color); }
.event .what { flex: 1; min-width: 0; }
.event .when { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; }
.settings-head { display: flex; align-items: center; gap: 12px; }
.annika-tile-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; align-items: start; }
.settings-tiles { display: contents; }
@container (max-width: 760px) { .annika-heating .zones { grid-template-columns: minmax(0, 1fr); } }`)

  function annika() {
    if (!window.Annika) throw new Error(`${CARD}: annika-common.js is not loaded`)
    return window.Annika
  }

  class AnnikaHeatingCard extends HTMLElement {
    setConfig(config) {
      // The old way: a list of climate entities, drawn by annika-ac-tiles-card.
      if (!config.entity) {
        if (!Array.isArray(config.entities) || config.entities.length === 0) {
          throw new Error(`${CARD}: "entity" is required (or a non-empty "entities" list of climate entities)`)
        }
        this._legacy = true
        if (!this._card) {
          const AcCard = customElements.get('annika-ac-tiles-card')
          if (!AcCard) throw new Error(`${CARD}: annika-ac-tiles-card.js is not loaded`)
          this._card = new AcCard()
          this.innerHTML = ''
          this.appendChild(this._card)
        }
        this._card.setConfig(config)
        if (this._hass) this._card.hass = this._hass
        return
      }
      this._legacy = false
      this._config = config
      this._structure = ''
      this._chartMode = {}
      this._sched = { zone: null, day: null }
      this._pop = null
      this._settings = null
      this._tiles = {}
      this._history = {}
      this._historyAt = 0
      this._historyBusy = false
      this._historyVersion = 0
      this._notice = ''
      this._render()
    }

    connectedCallback() {
      if (this._legacy) return
      this._structure = ''
      this._tick = setInterval(() => this._refresh(), TICK_MS)
      this._outside = (event) => {
        if (this._pop && !event.composedPath().some((el) => el.classList && (el.classList.contains('popover') || (el.dataset && (el.dataset.popOpen !== undefined))))) {
          this._pop = null
          this._render(true)
        }
      }
      document.addEventListener('click', this._outside)
      if (this._config && this._hass) this._render()
    }

    disconnectedCallback() {
      clearInterval(this._tick)
      this._tick = null
      if (this._outside) document.removeEventListener('click', this._outside)
    }

    set hass(hass) {
      this._hass = hass
      if (this._legacy) {
        if (this._card) this._card.hass = hass
        return
      }
      this._render()
      Object.values(this._tiles).forEach((el) => (el.hass = hass))
    }

    getCardSize() {
      return this._legacy && this._card ? this._card.getCardSize() : 12
    }

    getGridOptions() {
      return this._legacy && this._card ? this._card.getGridOptions() : { columns: 'full' }
    }

    getLayoutOptions() {
      return this._legacy && this._card ? this._card.getLayoutOptions() : { grid_columns: 'full' }
    }

    get _lang() {
      const lang = window.Annika && window.Annika.language
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
      return Promise.resolve(this._hass.callService(SERVICE_DOMAIN, service, { entity_id: this._config.entity, ...data })).catch((error) => {
        this._notice = (error && error.message) || this._texts.error
        this._render(true)
      })
    }

    _icon(name) {
      return `<ha-icon icon="${name}"></ha-icon>`
    }

    _stateOf(entityId) {
      return this._hass && this._hass.states[entityId]
    }

    // --- formatting -------------------------------------------------------------

    _time(value) {
      const date = value instanceof Date ? value : new Date(value)
      return date.toLocaleTimeString(this._lang, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    }

    _when(iso) {
      const date = new Date(iso)
      const t = this._texts
      const clock = this._time(date)
      const now = new Date()
      if (date.toDateString() === now.toDateString()) return clock
      const yesterday = new Date(now.getTime() - 86400000)
      if (date.toDateString() === yesterday.toDateString()) return fill(t.yesterday, { time: clock })
      return `${date.toLocaleDateString(this._lang, { month: 'short', day: 'numeric' })} ${clock}`
    }

    _at(iso) {
      const date = new Date(iso)
      const clock = this._time(date)
      return date.toDateString() === new Date().toDateString() ? clock : fill(this._texts.tomorrow, { time: clock })
    }

    _duration(minutes) {
      return minutes % 60 === 0 ? `${minutes / 60} ${this._texts.hours}` : `${minutes} ${this._texts.min}`
    }

    // --- what the thermostats are doing -----------------------------------------

    _current(entityId) {
      const state = this._stateOf(entityId)
      const value = state && parseFloat(state.attributes && state.attributes.current_temperature)
      return Number.isFinite(value) ? value : null
    }

    _heating(entityId) {
      const state = this._stateOf(entityId)
      return !!state && state.attributes && state.attributes.hvac_action === 'heating'
    }

    _thermostatName(config, entity) {
      for (const zone of config.zones) {
        const found = zone.thermostats.find((th) => th.entity === entity)
        if (found) return found.name
      }
      return entity
    }

    _zoneName(config, id) {
      const zone = config.zones.find((item) => item.id === id)
      return zone ? zone.name : id
    }

    _zoneInfo(config, state, zone) {
      const temps = zone.thermostats.map((th) => this._current(th.entity)).filter((value) => value !== null)
      const heating = zone.thermostats.filter((th) => this._heating(th.entity)).length
      return {
        average: temps.length ? temps.reduce((sum, value) => sum + value, 0) / temps.length : null,
        heating,
        total: zone.thermostats.length,
        temps: zone.thermostats.map((th) => this._current(th.entity)),
        flags: zone.thermostats.map((th) => this._heating(th.entity)),
        state: state[zone.id] || {},
      }
    }

    // --- history ------------------------------------------------------------------

    _refresh() {
      if (!this._config || !this._hass) return
      this._loadHistory()
      this._render(true)
    }

    async _loadHistory(force) {
      const stateObj = this._stateObj
      if (!stateObj || !stateObj.attributes.config || this._historyBusy || !this._hass.callWS) return
      if (!force && Date.now() - this._historyAt < HISTORY_MS) return
      const entities = stateObj.attributes.config.zones.flatMap((zone) => zone.thermostats.map((th) => th.entity))
      if (!entities.length) return
      this._historyBusy = true
      this._historyAt = Date.now()
      try {
        const start = new Date()
        start.setHours(0, 0, 0, 0)
        const result = await this._hass.callWS({
          type: 'history/history_during_period',
          start_time: start.toISOString(),
          end_time: new Date().toISOString(),
          entity_ids: entities,
          include_start_time_state: true,
          significant_changes_only: false,
          minimal_response: false,
          no_attributes: false,
        })
        const history = {}
        for (const entity of entities) history[entity] = this._parseHistory((result || {})[entity] || [], start.getTime())
        this._history = history
        this._historyVersion += 1
        this._render(true)
      } catch (error) {
        // The chart shows what the thermostats say now.
      } finally {
        this._historyBusy = false
      }
    }

    // [{ t, cur, target }]: the temperature and the target (null when it is off) over time.
    _parseHistory(states, from) {
      const points = []
      let attributes = {}
      for (const item of states) {
        attributes = { ...attributes, ...(item.a || item.attributes || {}) }
        const seconds = item.lu !== undefined ? item.lu : item.last_updated ? Date.parse(item.last_updated) / 1000 : null
        if (seconds === null) continue
        const state = item.s !== undefined ? item.s : item.state
        const cur = parseFloat(attributes.current_temperature)
        const target = state === 'off' || state === 'unavailable' || state === 'unknown' ? null : parseFloat(attributes.temperature)
        points.push({ t: Math.max(seconds * 1000, from), cur: Number.isFinite(cur) ? cur : null, target: Number.isFinite(target) ? target : null })
      }
      return points.sort((a, b) => a.t - b.t)
    }

    // The value of a series at a time: the last point before it.
    _at_(points, time, key) {
      let value = null
      for (const point of points) {
        if (point.t > time) break
        value = point[key]
      }
      return value
    }

    _series(config, zone, mode, now, start) {
      const buckets = []
      for (let time = start; time <= now; time += BUCKET_MS) buckets.push(time)
      if (buckets[buckets.length - 1] !== now) buckets.push(now)
      const fromState = (entity) => {
        const state = this._stateOf(entity)
        const cur = this._current(entity)
        const target = state && state.state !== 'off' && state.state !== 'unavailable' && state.state !== 'unknown' ? parseFloat(state.attributes && state.attributes.temperature) : null
        return { cur, target: Number.isFinite(target) ? target : null }
      }
      const lines = zone.thermostats.map((th, index) => {
        const points = this._history[th.entity] || []
        const values = buckets.map((time) => (time === now ? fromState(th.entity).cur : this._at_(points, time, 'cur')))
        return { id: th.entity, name: th.name, color: PALETTE[index % PALETTE.length], values }
      })
      const average = buckets.map((_, at) => {
        const present = lines.map((line) => line.values[at]).filter((value) => value !== null && value !== undefined)
        return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null
      })
      // The target of the zone at each time: the one most thermostats had.
      const targets = buckets.map((time) => {
        const values = zone.thermostats
          .map((th) => (time === now ? fromState(th.entity).target : this._at_(this._history[th.entity] || [], time, 'target')))
          .filter((value) => value !== null && value !== undefined)
        if (!values.length) return null
        const counts = new Map()
        values.forEach((value) => counts.set(value, (counts.get(value) || 0) + 1))
        return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0][0]
      })
      return { buckets, lines: mode === 'rooms' ? lines : [{ id: zone.id, name: this._texts.temperature, color: 'var(--primary-color, #33C46E)', values: average }], targets }
    }

    _chartHtml(config, zone, info, mode, t) {
      const W = 640
      const H = 190
      const L = 34
      const R = 8
      const T = 10
      const B = 22
      const start = new Date()
      start.setHours(0, 0, 0, 0)
      const now = Date.now()
      const day = 86400000
      const series = this._series(config, zone, mode, now, start.getTime())
      const plan = (info.state.plan || []).map((item) => ({ t: Date.parse(item.time), target: item.target }))
      const current = info.state.target
      const numbers = [
        ...series.lines.flatMap((line) => line.values),
        ...series.targets,
        ...plan.map((item) => item.target),
        current,
      ].filter(isNumber)
      if (!numbers.length) return ''
      let min = Math.floor(Math.min(...numbers) - 1)
      let max = Math.ceil(Math.max(...numbers) + 1)
      if (max - min < 4) {
        const mid = (max + min) / 2
        min = Math.floor(mid - 2)
        max = min + 4
      }
      const stepY = max - min > 8 ? 2 : 1
      const x = (time) => L + ((W - L - R) * (time - start.getTime())) / day
      const y = (value) => T + (H - T - B) * (1 - (value - min) / (max - min))
      let svg = ''
      for (let value = min; value <= max; value += stepY) {
        svg += `<line x1="${L}" x2="${W - R}" y1="${y(value)}" y2="${y(value)}" stroke="rgba(255,255,255,.06)"/><text x="${L - 6}" y="${y(value) + 4}" fill="rgba(232,232,230,.45)" font-size="10" text-anchor="end">${value}°</text>`
      }
      for (let hour = 0; hour <= 24; hour += 3) {
        svg += `<text x="${x(start.getTime() + hour * 3600000)}" y="${H - 6}" fill="rgba(232,232,230,.45)" font-size="10" text-anchor="middle">${String(hour).padStart(2, '0')}</text>`
      }
      // Pieces of a line, broken where there is no value.
      const pieces = (values, step) => {
        const out = []
        let piece = []
        series.buckets.forEach((time, at) => {
          const value = values[at]
          if (value === null || value === undefined) {
            if (piece.length) out.push(piece)
            piece = []
            return
          }
          if (step && piece.length) piece.push(`${x(time)},${y(piece.last)}`)
          piece.push(`${x(time)},${y(value)}`)
          piece.last = value
        })
        if (piece.length) out.push(piece)
        return out
      }
      for (const points of pieces(series.targets, true)) {
        svg += `<polyline points="${points.join(' ')}" fill="none" stroke="var(--warning-color, #D9954B)" stroke-width="2"/>`
      }
      // What is planned from now on, as steps.
      if (isNumber(current)) {
        let level = current
        let last = now
        let path = `${x(now)},${y(level)}`
        for (const item of plan) {
          path += ` ${x(item.t)},${y(level)} ${x(item.t)},${y(item.target)}`
          level = item.target
          last = item.t
        }
        path += ` ${x(start.getTime() + day)},${y(level)}`
        svg += `<polyline points="${path}" fill="none" stroke="var(--warning-color, #D9954B)" stroke-width="2" stroke-dasharray="5 4" opacity=".7"/>`
        void last
      }
      for (const line of series.lines) {
        for (const points of pieces(line.values, false)) {
          svg += `<polyline points="${points.join(' ')}" fill="none" stroke="${line.color}" stroke-width="${mode === 'rooms' ? 1.6 : 2}" stroke-linejoin="round"/>`
        }
      }
      svg += `<line x1="${x(now)}" x2="${x(now)}" y1="${T}" y2="${H - B}" stroke="#fff" stroke-width="1.5"/>`
      return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t.temperature)}">${svg}</svg></div>`
    }

    _legendHtml(zone, mode, info, t) {
      const target = `<span><i style="background:var(--warning-color, #D9954B)"></i>${escapeHtml(t.target)}</span>`
      const planned = `<span><i style="background:repeating-linear-gradient(90deg,var(--warning-color, #D9954B) 0 4px,transparent 4px 7px)"></i>${escapeHtml(t.planned)}</span>`
      if (mode === 'rooms') {
        const rooms = zone.thermostats
          .map((th, index) => `<span><i style="background:${PALETTE[index % PALETTE.length]}"></i>${escapeHtml(th.name)}</span>`)
          .join('')
        return `<div class="legend">${rooms}${target}${planned}</div>`
      }
      return `<div class="legend"><span><i style="background:var(--primary-color, #33C46E)"></i>${escapeHtml(t.temperature)}</span>${target}${planned}</div>`
    }

    // --- the strip ------------------------------------------------------------------

    _stripHtml(config, state, t) {
      const forecast = config.weather && this._stateOf(config.weather)
      const temp = forecast && forecast.attributes && Number.isFinite(parseFloat(forecast.attributes.temperature))
        ? deg(parseFloat(forecast.attributes.temperature)) : ''
      let sub = t.master_off
      if (config.enabled) {
        if (config.season.active === true && config.weather && config.season.enabled && temp) sub = fill(t.season_on, { temp })
        else if (config.season.active === false) sub = fill(t.season_off, { temp })
        else sub = t.season_any
      }
      const entity = config.entities && config.entities.master
      // The switch is Home Assistant's own tile with its toggle; until the entity exists, a plain tile says the same.
      const master = entity
        ? `<div class="master-host" data-master-tile="${escapeHtml(entity)}"></div>`
        : `<ha-card class="stile ${config.enabled ? '' : 'off'}">
        <div class="ico">${this._icon('mdi:home-thermometer')}</div>
        <div class="txt"><div class="t">${escapeHtml(t.heating)}</div><div class="s">${escapeHtml(sub)}</div></div>
      </ha-card>`
      const boilers = config.boilers.map((boiler) => {
        const on = (this._stateOf(boiler.entity) || {}).state === 'on'
        const zones = config.zones.filter((zone) => boiler.zones.includes(zone.id))
        const members = zones.flatMap((zone) => zone.thermostats)
        const heating = members.filter((th) => this._heating(th.entity)).length
        const text = on ? `${t.running} · ${fill(t.of_heating, { n: heating, total: members.length })}` : t.boiler_idle
        return `<ha-card class="stile ${on ? 'heat' : 'idle'}">
          <div class="ico">${this._icon('mdi:radiator')}</div>
          <div class="txt"><div class="t">${escapeHtml(boiler.name || t.boiler)}</div><div class="s">${escapeHtml(text)}</div></div>
        </ha-card>`
      }).join('')
      return `<div class="strip">${master}${boilers}</div>`
    }

    // --- the zones ------------------------------------------------------------------

    _targetText(value) {
      return isNumber(value) ? `${Number(value).toFixed(1)}<small>°C</small>` : escapeHtml(this._texts.off)
    }

    _whyHtml(config, zone, info, t) {
      const state = info.state
      const lines = []
      const total = info.total
      if (info.average !== null) {
        lines.push(`<div class="now">${total > 1
          ? fill(t.now_avg, { temp: `<b>${deg(info.average)}</b>`, n: info.heating, total })
          : fill(t.now_one, { temp: `<b>${deg(info.average)}</b>`, state: escapeHtml(info.heating ? t.heating_now : t.not_heating) })}</div>`)
      }
      const manual = (state.manual || []).length
      const hasSchedule = Object.values(zone.schedule).some((slots) => slots.length)
      if (manual && manual === total) lines.push(`<div class="line">${this._icon('mdi:hand-back-right')}<span>${escapeHtml(t.manual_line)}</span></div>`)
      else if (manual) lines.push(`<div class="line">${this._icon('mdi:hand-back-right')}<span>${escapeHtml(t.manual_mixed)}</span></div>`)
      if (state.slot && manual < total) {
        lines.push(`<div class="line">${this._icon(state.slot.conditional ? 'mdi:motion-sensor' : 'mdi:calendar-clock')}<span><b>${escapeHtml(state.slot.name || '')}</b> · ${escapeHtml(fill(t.since, { target: deg(state.target), time: this._time(state.slot.since) }))}</span></div>`)
      } else if (!manual) {
        if (config.season.active === false) lines.push(`<div class="line">${this._icon('mdi:weather-sunny')}<span>${escapeHtml(t.season_line)}</span></div>`)
        else if (!hasSchedule) lines.push(`<div class="line">${this._icon('mdi:hand-back-right')}<span>${escapeHtml(t.empty_line)}</span></div>`)
        else lines.push(`<div class="line">${this._icon('mdi:calendar-remove')}<span>${escapeHtml(t.none_line)}</span></div>`)
      }
      if (state.next && config.season.active !== false) {
        const values = { name: `<b>${escapeHtml(state.next.name || '')}</b>`, time: this._at(state.next.time), target: deg(state.next.target) }
        const text = state.next.conditional ? fill(t.next_if, { ...values, minutes: this._duration(state.next.minutes) }) : fill(t.next, values)
        lines.push(`<div class="line">${this._icon(state.next.conditional ? 'mdi:motion-sensor' : 'mdi:clock-outline')}<span>${text}</span></div>`)
      }
      return lines.join('')
    }

    _roomHtml(config, zone, th, info, cols, t) {
      const view = (info.state.thermostats || {})[th.entity] || { value: 'off', source: 'none' }
      const heating = this._heating(th.entity)
      const current = this._current(th.entity)
      const off = view.value === 'off'
      const manual = view.source === 'manual'
      const foot = heating
        ? `<span class="f">${this._icon('mdi:fire')}${escapeHtml(t.heating_status)}</span>`
        : `<span>${escapeHtml(off ? t.off : t.idle)}</span>`
      return `<div class="room ${heating ? 'heating' : ''} ${manual ? 'override' : ''} ${off ? 'off' : ''}">
        <div class="top"><div class="badge">${this._icon(th.icon || 'mdi:thermostat')}</div><div class="nm" title="${escapeHtml(th.name)}">${escapeHtml(th.name)}</div>
          <button class="gear" data-gear="${escapeHtml(th.entity)}" title="${escapeHtml(t.settings)}">${this._icon('mdi:cog')}</button></div>
        <div class="mid"><div class="cur">${current === null ? '–' : deg(current)}</div>
          <div class="step"><button data-th-step="${escapeHtml(th.entity)}|-1" aria-label="${escapeHtml(t.lower)}">${this._icon('mdi:minus')}</button><span class="v">${off ? escapeHtml(t.off) : deg(view.value)}</span><button data-th-step="${escapeHtml(th.entity)}|1" aria-label="${escapeHtml(t.raise)}">${this._icon('mdi:plus')}</button></div></div>
        <div class="foot">${foot}${manual ? `<button class="pill small warn" data-th-auto="${escapeHtml(th.entity)}">${escapeHtml(t.auto)}</button>` : ''}</div>
      </div>`
    }

    _zoneHtml(config, zone, info, t, full) {
      const mode = this._chartMode[zone.id] || 'zone'
      const state = info.state
      const manual = (state.manual || []).length
      const boiler = config.boilers.find((item) => item.id === zone.boiler)
      const off = !isNumber(state.target)
      const cols = Math.min(4, zone.thermostats.length)
      const toggle = zone.thermostats.length > 1
        ? `<div class="chart-toggle"><button class="pill small ${mode === 'zone' ? 'sel' : ''}" data-chart="${escapeHtml(zone.id)}|zone">${escapeHtml(t.zone)}</button><button class="pill small ${mode === 'rooms' ? 'sel' : ''}" data-chart="${escapeHtml(zone.id)}|rooms">${escapeHtml(t.rooms)}</button></div>`
        : ''
      const chart = this._chartHtml(config, zone, info, zone.thermostats.length > 1 ? mode : 'zone', t)
      return `<ha-card class="zone ${full ? 'full' : ''}">
        <div class="zone-head">
          <div class="name">${escapeHtml(zone.name)}${boiler ? ` <span class="tag">${this._icon('mdi:radiator')}${escapeHtml(boiler.name)}</span>` : ''}</div>
          <div class="right">${manual ? `<span class="tag manual">${this._icon('mdi:hand-back-right')}${escapeHtml(fill(t.manual_n, { n: manual }))}</span><button class="pill small warn" data-zone-auto="${escapeHtml(zone.id)}">${escapeHtml(t.auto)}</button>` : ''}</div>
        </div>
        <div class="zone-main">
          <div class="dial">
            <button class="round" data-zone-step="${escapeHtml(zone.id)}|-1" aria-label="${escapeHtml(t.lower)}">${this._icon('mdi:minus')}</button>
            <div class="bigtemp ${off ? 'off' : ''}">${this._targetText(state.target)}</div>
            <button class="round" data-zone-step="${escapeHtml(zone.id)}|1" aria-label="${escapeHtml(t.raise)}">${this._icon('mdi:plus')}</button>
          </div>
          <div class="why">${this._whyHtml(config, zone, info, t)}</div>
        </div>
        ${chart ? `<div class="chart-wrap">${toggle}${chart}</div>` : ''}${chart ? this._legendHtml(zone, zone.thermostats.length > 1 ? mode : 'zone', info, t) : ''}
        <div class="rooms" style="--cols:${cols}">${zone.thermostats.map((th) => this._roomHtml(config, zone, th, info, cols, t)).join('')}</div>
      </ha-card>`
    }

    _zonesHtml(config, state, t) {
      const infos = config.zones.map((zone) => this._zoneInfo(config, state, zone))
      return `<div class="zones">${config.zones.map((zone, at) => this._zoneHtml(config, zone, infos[at], t, false)).join('')}</div>`
    }

    // --- the schedule ---------------------------------------------------------------

    _days(config) {
      return config.day_keys || ['workday', 'non_workday']
    }

    // The words for a day type: workday / non-workday (by a sensor, or Mon-Fri / Sat-Sun), or a day of the week.
    _dayLabel(config, key, lower) {
      const t = this._texts
      let label
      if (WEEKDAYS.includes(key)) {
        label = new Date(2024, 0, 1 + WEEKDAYS.indexOf(key)).toLocaleDateString(this._lang, { weekday: 'long' })
        label = label.charAt(0).toUpperCase() + label.slice(1)
      } else if (config.day_mode === 'weekend') label = key === 'workday' ? t.weekday : t.weekend
      else label = t[key]
      return lower ? label.toLowerCase() : label
    }

    _todayText(config) {
      const t = this._texts
      if (config.day_mode === 'days') return fill(t.today_is_day, { day: this._dayLabel(config, config.day_type, true) })
      if (config.day_mode === 'weekend') return fill(t.today_is_day, { day: this._dayLabel(config, config.day_type, false) })
      return fill(t.today_is, { day: this._dayLabel(config, config.day_type, true) })
    }

    _selected(config) {
      const zone = config.zones.find((item) => item.id === this._sched.zone) || config.zones[0]
      const day = this._days(config).includes(this._sched.day) ? this._sched.day : config.day_type
      return { zone, day }
    }

    _barHtml(slots, isToday, t) {
      const sorted = [...slots].sort((a, b) => minutesOf(a.time) - minutesOf(b.time))
      if (!sorted.length) return `<div class="bar"><div class="seg none" style="width:100%">${escapeHtml(t.off)}</div></div>`
      const targets = sorted.map((slot) => slot.target)
      const lo = Math.min(...targets)
      const hi = Math.max(...targets)
      const color = (value) => {
        const k = hi === lo ? 0.5 : (value - lo) / (hi - lo)
        const a = [33, 120, 70]
        const b = [217, 149, 75]
        return `rgb(${a.map((c, i) => Math.round(c + (b[i] - c) * k)).join(',')})`
      }
      const segments = []
      const first = minutesOf(sorted[0].time)
      if (first > 0) segments.push({ from: 0, to: first, slot: sorted[sorted.length - 1] })
      sorted.forEach((slot, at) => segments.push({ from: minutesOf(slot.time), to: at + 1 < sorted.length ? minutesOf(sorted[at + 1].time) : 1440, slot }))
      const html = segments
        .filter((segment) => segment.to > segment.from)
        .map((segment) => {
          const width = ((segment.to - segment.from) / 1440) * 100
          const label = width >= 12 ? `${segment.slot.name || segment.slot.time} · ${Number(segment.slot.target).toFixed(0)}°` : ''
          return `<div class="seg ${segment.slot.motion ? 'cond' : ''}" style="width:${width}%;background-color:${color(segment.slot.target)}" title="${escapeHtml(`${segment.slot.name || ''} ${segment.slot.time} · ${deg(segment.slot.target)}`)}">${escapeHtml(label)}</div>`
        })
        .join('')
      let line = ''
      if (isToday) {
        const now = new Date()
        line = `<div class="nowline" style="left:${((now.getHours() * 60 + now.getMinutes()) / 1440) * 100}%"></div>`
      }
      return `<div class="bar">${html}${line}</div>`
    }

    _roomsLabel(zone, slot, t) {
      const names = slot.thermostats.map((entity) => (zone.thermostats.find((th) => th.entity === entity) || {}).name || entity)
      if (!names.length || names.length === zone.thermostats.length) return t.all_rooms
      return names.length === 1 ? names[0] : fill(t.rooms_n, { n: names.length })
    }

    _sensorsLabel(config, slot, t) {
      const names = slot.motion.sensors.map((entity) => (config.motion_sensors.find((item) => item.entity === entity) || {}).name || entity)
      if (!names.length) return t.choose_sensors
      return names.length <= 2 ? names.join(', ') : fill(t.motion_sensors_n, { n: names.length })
    }

    _slotRowHtml(config, zone, slot, t) {
      const id = escapeHtml(slot.id)
      const motion = slot.motion
        ? `<div class="cond">${this._icon('mdi:motion-sensor')} ${escapeHtml(t.no_motion_in)}
            <button class="dd" data-pop-open data-slot-sensors="${id}">${escapeHtml(this._sensorsLabel(config, slot, t))}</button>
            ${escapeHtml(t.for)} <span class="u"><input type="number" min="1" max="1440" value="${slot.motion.minutes}" data-slot-minutes="${id}"> ${escapeHtml(t.min)}</span>
            <button class="iconbtn" data-slot-nocond="${id}" title="${escapeHtml(t.remove_condition)}">${this._icon('mdi:close')}</button></div>`
        : `<button class="dd empty" data-pop-open data-slot-addcond="${id}">${escapeHtml(t.no_condition)}</button>`
      return `<tr>
        <td><input type="time" value="${escapeHtml(slot.time)}" data-slot-time="${id}"></td>
        <td><input type="text" value="${escapeHtml(slot.name)}" placeholder="${escapeHtml(t.slot_name)}" maxlength="40" style="width:130px" data-slot-name="${id}"></td>
        <td>${motion}</td>
        <td><span class="stepper"><button data-slot-step="${id}|-1" aria-label="${escapeHtml(t.lower)}">${this._icon('mdi:minus')}</button><span class="v">${deg(slot.target)}</span><button data-slot-step="${id}|1" aria-label="${escapeHtml(t.raise)}">${this._icon('mdi:plus')}</button></span></td>
        <td>${zone.thermostats.length > 1
          ? `<button class="dd" data-pop-open data-slot-rooms="${id}">${escapeHtml(this._roomsLabel(zone, slot, t))}</button>`
          : `<span class="muted">${escapeHtml(zone.thermostats[0].name)}</span>`}</td>
        <td class="act-cell"><button class="iconbtn" data-slot-del="${id}" title="${escapeHtml(t.delete)}">${this._icon('mdi:delete')}</button></td>
      </tr>`
    }

    _scheduleHtml(config, t) {
      const { zone, day } = this._selected(config)
      const slots = zone.schedule[day]
      const pills = config.zones.length > 1
        ? `<div class="row">${config.zones.map((item) => `<button class="pill small ${item.id === zone.id ? 'sel' : ''}" data-sched-zone="${escapeHtml(item.id)}">${escapeHtml(item.name)}</button>`).join('')}</div>`
        : ''
      const today = day === config.day_type
      const rows = [...slots].sort((a, b) => minutesOf(a.time) - minutesOf(b.time)).map((slot) => this._slotRowHtml(config, zone, slot, t)).join('')
      return `<div class="wide">
        <div class="sec"><span>${escapeHtml(t.schedule)}</span>${pills}</div>
        <ha-card class="panel">
          <div class="toolbar-row" style="margin-bottom:8px">
            <div class="row">${this._days(config).map((item) => `<button class="pill ${item === day ? 'sel' : ''}" data-sched-day="${item}">${escapeHtml(this._dayLabel(config, item))}</button>`).join('')}</div>
            <div class="muted">${escapeHtml(this._todayText(config))}</div>
          </div>
          ${this._barHtml(slots, today, t)}
          <div class="ticks">${[0, 3, 6, 9, 12, 15, 18, 21, 24].map((hour) => `<span>${String(hour).padStart(2, '0')}</span>`).join('')}</div>
        </ha-card>
        <ha-card class="panel table">
          ${slots.length ? `<table>
            <thead><tr><th>${escapeHtml(t.starts_at)}</th><th>${escapeHtml(t.name)}</th><th>${escapeHtml(t.only_if)}</th><th>${escapeHtml(t.target)}</th><th>${escapeHtml(t.applies_to)}</th><th></th></tr></thead>
            <tbody>${rows}</tbody></table>` : `<div class="muted" style="padding:12px 8px">${escapeHtml(t.no_slots)}</div>`}
          <div class="toolbar-row" style="padding:8px"><div class="row"><button class="pill" data-slot-add>${this._icon('mdi:plus')} ${escapeHtml(t.add_slot)}</button></div><span class="muted">${escapeHtml(t.slot_hint)}</span></div>
        </ha-card>
        <div class="notice">${escapeHtml(this._notice)}</div>
      </div>`
    }

    _popoverHtml(config, t) {
      if (!this._pop) return ''
      const { zone, day } = this._selected(config)
      const slot = zone.schedule[day].find((item) => item.id === this._pop.slot)
      if (!slot) return ''
      if (this._pop.kind === 'rooms') {
        const all = !slot.thermostats.length
        const rows = zone.thermostats
          .map((th) => `<label class="pop-row"><input type="checkbox" class="annika-check" data-pop-room="${escapeHtml(th.entity)}" ${all || slot.thermostats.includes(th.entity) ? 'checked' : ''}> ${escapeHtml(th.name)}</label>`)
          .join('')
        return `<div class="popover" data-popover><div class="pop-title">${escapeHtml(t.applies_to)}</div><div class="pop-sub">${escapeHtml(t.rooms_hint)}</div>${rows}</div>`
      }
      const chosen = slot.motion ? slot.motion.sensors : []
      const known = config.motion_sensors.map((item) => item.entity)
      const sensors = [...config.motion_sensors, ...chosen.filter((entity) => !known.includes(entity)).map((entity) => ({ entity, name: entity }))]
      const rows = sensors
        .map((sensor) => `<label class="pop-row"><input type="checkbox" class="annika-check" data-pop-sensor="${escapeHtml(sensor.entity)}" ${chosen.includes(sensor.entity) ? 'checked' : ''}> ${escapeHtml(sensor.name)}<span class="muted">${escapeHtml(sensor.entity)}</span></label>`)
        .join('')
      return `<div class="popover" data-popover><div class="pop-title">${escapeHtml(t.motion_sensors)}</div><div class="pop-sub">${escapeHtml(t.motion_hint)}</div>${rows}</div>`
    }

    _placePopover() {
      const pop = this.querySelector('[data-popover]')
      if (!pop || !this._pop) return
      const anchor = this.querySelector(`[data-slot-${this._pop.kind === 'rooms' ? 'rooms' : this._pop.add ? 'addcond' : 'sensors'}="${this._pop.slot}"]`)
        || this.querySelector(`[data-slot-addcond="${this._pop.slot}"]`) || this.querySelector(`[data-slot-sensors="${this._pop.slot}"]`)
      if (!anchor || !anchor.getBoundingClientRect) return
      // Placed inside the card, not on the window: a card with containment makes `fixed` relative to itself.
      const host = this.querySelector('.annika-heating')
      const box = anchor.getBoundingClientRect()
      const area = host.getBoundingClientRect()
      pop.style.left = `${Math.max(0, Math.min(box.left - area.left, area.width - pop.offsetWidth))}px`
      pop.style.top = `${box.bottom - area.top + 6}px`
    }

    // --- editing a schedule -----------------------------------------------------------

    _slotsOf(config) {
      const { zone, day } = this._selected(config)
      return { zone, day, slots: zone.schedule[day].map((slot) => JSON.parse(JSON.stringify(slot))) }
    }

    _editSlots(mutate) {
      const stateObj = this._stateObj
      if (!stateObj || !stateObj.attributes.config) return
      const { zone, day, slots } = this._slotsOf(stateObj.attributes.config)
      const next = mutate(slots, zone)
      if (!next) return
      this._notice = ''
      return this._service('set_heating_schedule', { zone: zone.id, day, slots: next })
    }

    _editSlot(id, change) {
      return this._editSlots((slots) => {
        const slot = slots.find((item) => item.id === id)
        if (!slot) return null
        change(slot)
        return slots
      })
    }

    _addSlot() {
      this._editSlots((slots) => {
        const taken = new Set(slots.map((slot) => slot.time))
        let minutes = 12 * 60
        while (taken.has(`${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`) && minutes < 1439) minutes += 1
        const time = `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
        return [...slots, { time, name: '', target: DEFAULT_TARGET, thermostats: [], motion: null }]
      })
    }

    // --- the automations ---------------------------------------------------------------

    _automationsHtml(config, t) {
      const season = config.season
      const forecast = config.weather && this._stateOf(config.weather)
      const value = forecast && parseFloat(forecast.attributes && forecast.attributes.temperature)
      const status = Number.isFinite(value) && season.active !== null && season.active !== undefined
        ? `<div class="params">${escapeHtml(fill(t.season_now, { state: season.active ? t.season_in : t.season_out, temp: deg(value) }))}</div>` : ''
      const body = config.weather
        ? `<div class="params">${escapeHtml(t.season_below)} <span class="u"><input type="number" step="0.5" value="${season.on_below}" data-season="on_below">°</span> ${escapeHtml(t.season_for)} <span class="u"><input type="number" min="1" max="72" value="${season.hours}" data-season="hours"> ${escapeHtml(t.hours)}</span></div>
           <div class="params">${escapeHtml(t.season_above)} <span class="u"><input type="number" step="0.5" value="${season.off_above}" data-season="off_above">°</span> ${escapeHtml(t.season_for)} <span class="u"><input type="number" min="1" max="72" value="${season.hours}" data-season="hours"> ${escapeHtml(t.hours)}</span></div>${status}`
        : `<div class="params">${escapeHtml(t.no_weather)}</div>`
      return `<div class="wide">
        <div class="sec" data-heading="${escapeHtml(t.automations)}">${escapeHtml(t.automations)}</div>
        <ha-card class="panel"><div class="rule ${season.enabled && config.weather ? '' : 'off'}"><div class="body">
          <div class="title">${config.weather ? `<input type="checkbox" class="annika-check" ${season.enabled ? 'checked' : ''} data-season-enabled>` : ''} ${escapeHtml(t.season)}</div>${body}</div></div></ha-card>
      </div>`
    }

    // --- the activity --------------------------------------------------------------------

    _eventView(config, event, t) {
      const who = event.thermostat ? this._thermostatName(config, event.thermostat) : this._zoneName(config, event.zone)
      const target = event.target === 'off' ? t.off : isNumber(event.target) ? deg(event.target) : ''
      switch (event.kind) {
        case 'slot':
          return { icon: 'mdi:calendar-clock', tone: 'heat', text: fill(t.ev_slot, { zone: this._zoneName(config, event.zone), target, name: event.name || '' }) }
        case 'manual':
          return {
            icon: 'mdi:hand-back-right',
            tone: 'heat',
            text: fill(event.target === 'off' ? t.ev_manual_off : event.external ? t.ev_manual_external : t.ev_manual, { who, target }),
          }
        case 'auto':
          return { icon: 'mdi:autorenew', tone: 'ok', text: fill(t.ev_auto, { who }) }
        case 'boiler': {
          const boiler = (config.boilers.find((item) => item.id === event.boiler) || {}).name || t.boiler
          const text = fill(event.on ? t.ev_boiler_on : t.ev_boiler_off, { boiler })
          return { icon: 'mdi:radiator', tone: event.on ? 'ok' : '', text: event.on && event.who ? `${text} · ${fill(t.ev_boiler_who, { who: event.who })}` : text }
        }
        case 'season':
          return { icon: 'mdi:weather-pouring', tone: '', text: fill(event.on ? t.ev_season_on : t.ev_season_off, { temp: isNumber(event.temperature) ? deg(event.temperature) : '' }) }
        case 'master':
          return { icon: 'mdi:power', tone: event.on ? 'ok' : '', text: event.on ? t.ev_master_on : t.ev_master_off }
        default:
          return { icon: 'mdi:information-outline', tone: '', text: String(event.kind) }
      }
    }

    _activityHtml(config, events, t) {
      const rows = events.slice(0, 12).map((event) => {
        const view = this._eventView(config, event, t)
        return `<div class="event"><div class="avatar ${view.tone}">${this._icon(view.icon)}</div><div class="what">${escapeHtml(view.text)}</div><div class="when">${escapeHtml(this._when(event.time))}</div></div>`
      }).join('')
      return `<div class="wide">
        <div class="sec" data-heading="${escapeHtml(t.activity)}">${escapeHtml(t.activity)}</div>
        <ha-card class="panel">${rows ? `<div class="events">${rows}</div>` : `<div class="muted">${escapeHtml(t.no_activity)}</div>`}</ha-card>
      </div>`
    }

    // --- the settings of a thermostat ----------------------------------------------------------

    _deviceName(id, device) {
      const state = this._hass.states[id]
      const name = (state.attributes && state.attributes.friendly_name) || id
      const registered = this._hass.devices && this._hass.devices[device]
      const prefix = registered && (registered.name_by_user || registered.name)
      return prefix && name.length > prefix.length + 1 && name.startsWith(`${prefix} `) ? name.slice(prefix.length + 1) : name
    }

    _settingEntities(entity) {
      const registry = (this._hass && this._hass.entities) || {}
      const states = (this._hass && this._hass.states) || {}
      const device = registry[entity] && registry[entity].device_id
      if (!device) return []
      const rank = (id) => {
        const at = SETTING_DOMAINS.indexOf(id.split('.')[0])
        return at < 0 ? SETTING_DOMAINS.length : at
      }
      return Object.keys(registry)
        .filter((id) => registry[id].device_id === device && !registry[id].hidden && !registry[id].hidden_by && states[id])
        .filter((id) => id !== entity && !HIDDEN_DOMAINS.includes(id.split('.')[0]))
        .sort((a, b) => rank(a) - rank(b) || this._deviceName(a, device).localeCompare(this._deviceName(b, device)))
    }

    _settingTile(id, name) {
      const domain = id.split('.')[0]
      const attrs = (this._hass.states[id] && this._hass.states[id].attributes) || {}
      let features = []
      if (domain === 'select') features = [{ type: 'select-options' }]
      else if (domain === 'number') features = [{ type: 'numeric-input', style: attrs.mode === 'box' ? 'buttons' : 'slider' }]
      return annika().tileConfig({ entity: id, name, color: 'primary' }, { features })
    }

    _settingsHtml(config, t) {
      const entity = this._settings
      const empty = this._settingEntities(entity).length === 0
      const name = this._thermostatName(config, entity)
      return `<div class="wide">
        <div class="settings-head">
          <button class="pill back" data-back title="${escapeHtml(t.back)}">${this._icon('mdi:arrow-left')}${escapeHtml(t.back)}</button>
          <div class="sec" data-heading="${escapeHtml(`${name} · ${t.settings}`)}">${escapeHtml(name)} · ${escapeHtml(t.settings)}</div>
        </div>
        <div class="annika-tile-row"><span data-main-tile></span><span class="settings-tiles" data-settings-tiles></span></div>
        ${empty ? `<div class="muted">${escapeHtml(t.no_settings)}</div>` : ''}
      </div>`
    }

    async _mountSettings() {
      const entity = this._settings
      if (!entity || !window.loadCardHelpers) return
      try {
        const helpers = await window.loadCardHelpers()
        const ids = [entity, ...this._settingEntities(entity)]
        const elements = []
        for (const id of ids) {
          if (!this._tiles[id]) {
            const element = await helpers.createCardElement(this._settingTile(id, id === entity ? this._thermostatName(this._stateObj.attributes.config, entity) : this._deviceName(id, this._hass.entities[id] && this._hass.entities[id].device_id)))
            element.hass = this._hass
            this._tiles[id] = element
          }
          elements.push(this._tiles[id])
        }
        const target = this._settings === entity && this.querySelector('[data-settings-tiles]')
        const main = this.querySelector('[data-main-tile]')
        if (target) {
          main.replaceChildren(elements[0])
          target.replaceChildren(...elements.slice(1))
        }
      } catch (error) {
        // Nothing to show: the heading stays.
      }
    }

    async _mountMaster() {
      const host = this.querySelector('[data-master-tile]')
      if (!host || !window.loadCardHelpers) return
      const entity = host.dataset.masterTile
      try {
        const helpers = await window.loadCardHelpers()
        const key = `master:${entity}`
        if (!this._tiles[key]) {
          this._tiles[key] = await helpers.createCardElement(
            annika().tileConfig({ entity, name: this._texts.heating, icon: 'mdi:home-thermometer', color: 'primary' }, { features: [{ type: 'toggle' }], features_position: 'inline' }),
          )
        }
        const tile = this._tiles[key]
        tile.hass = this._hass
        const current = this.querySelector('[data-master-tile]')
        if (current) current.replaceChildren(tile)
      } catch (error) {
        // The strip keeps its other tiles.
      }
    }

    _bodyElement() {
      if (!this._body) {
        this._body = document.createElement('div')
        this.appendChild(this._body)
      }
      return this._body
    }

    // --- rendering ------------------------------------------------------------------------------

    _render(force) {
      if (this._legacy || !this._config) return
      const stateObj = this._stateObj
      const t = this._texts
      if (!stateObj) {
        this._bodyElement().innerHTML = `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">${escapeHtml(fill(t.missing, { entity: this._config.entity }))}</div></ha-card>`
        this._structure = ''
        return
      }
      const config = stateObj.attributes.config
      if (!config) return
      const state = stateObj.attributes.state || {}
      const events = stateObj.attributes.events || []
      if (this._settings && !config.zones.some((zone) => zone.thermostats.some((th) => th.entity === this._settings))) this._settings = null
      this._loadHistory()
      const live = config.zones.flatMap((zone) => zone.thermostats.map((th) => {
        const item = this._stateOf(th.entity)
        return [th.entity, item && item.state, item && item.attributes && item.attributes.current_temperature, item && item.attributes && item.attributes.hvac_action]
      }))
      const boilers = config.boilers.map((boiler) => (this._stateOf(boiler.entity) || {}).state)
      const forecast = config.weather && this._stateOf(config.weather)
      const key = JSON.stringify([
        config, state, events, live, boilers, forecast && forecast.attributes && forecast.attributes.temperature, this._chartMode, this._sched,
        this._pop, this._settings, this._notice, this._historyVersion, Math.floor(Date.now() / 60000), t.heating,
      ])
      if (!force && key === this._structure) return
      this._structure = key
      const keep = this.offsetHeight
      if (keep) this.style.minHeight = `${keep}px`
      this._bodyElement().innerHTML = `
        <style>
          annika-heating-card { display: block; container-type: inline-size; }
          .annika-heating { display: block; position: relative; }
          ${(window.Annika && window.Annika.CHECKBOX_CSS) || ''}
          ${(window.Annika && window.Annika.SELECT_CSS) || ''}
          ${STYLE}
        </style>
        <div class="annika-heating">
          ${this._settings
            ? this._settingsHtml(config, t)
            : `${this._stripHtml(config, state, t)}${this._zonesHtml(config, state, t)}${this._scheduleHtml(config, t)}${this._automationsHtml(config, t)}${this._activityHtml(config, events, t)}${this._popoverHtml(config, t)}`}
        </div>
      `
      this._bind(config)
      this._placePopover()
      if (this._settings) this._mountSettings()
      else this._mountMaster()
      this._headings(this)
      requestAnimationFrame(() => { this.style.minHeight = '' })
    }

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
      } catch (error) {
        // The plain title stays.
      }
    }

    // --- acting ----------------------------------------------------------------------------------

    // The next target of a stepper: null turns it off, a number holds it.
    _stepped(current, direction) {
      if (!isNumber(current)) return direction > 0 ? DEFAULT_TARGET : null
      const next = Math.round((current + direction * STEP) * 10) / 10
      if (next < MIN_TARGET) return null
      return clamp(next)
    }

    _holdZone(zone, direction) {
      const stateObj = this._stateObj
      const state = ((stateObj && stateObj.attributes.state) || {})[zone] || {}
      const next = this._stepped(state.target, direction)
      if (next === null) {
        if (isNumber(state.target)) this._service('set_heating_manual', { zone, off: true })
        return
      }
      this._service('set_heating_manual', { zone, target: next })
    }

    _holdThermostat(entity, direction) {
      const stateObj = this._stateObj
      const state = (stateObj && stateObj.attributes.state) || {}
      const view = Object.values(state).map((zone) => (zone.thermostats || {})[entity]).find(Boolean)
      const current = view && isNumber(view.value) ? view.value : null
      const next = this._stepped(current, direction)
      if (next === null) {
        if (current !== null) this._service('set_heating_manual', { thermostats: [entity], off: true })
        return
      }
      this._service('set_heating_manual', { thermostats: [entity], target: next })
    }

    _bind(config) {
      const on = (selector, event, handler) =>
        this.querySelectorAll(selector).forEach((el) => el.addEventListener(event, (e) => handler(el, e)))
      const split = (value) => value.split('|')

      on('[data-zone-step]', 'click', (el) => {
        const [zone, direction] = split(el.dataset.zoneStep)
        this._holdZone(zone, Number(direction))
      })
      on('[data-th-step]', 'click', (el) => {
        const [entity, direction] = split(el.dataset.thStep)
        this._holdThermostat(entity, Number(direction))
      })
      on('[data-zone-auto]', 'click', (el) => this._service('set_heating_auto', { zone: el.dataset.zoneAuto }))
      on('[data-th-auto]', 'click', (el) => this._service('set_heating_auto', { thermostats: [el.dataset.thAuto] }))
      on('[data-chart]', 'click', (el) => {
        const [zone, mode] = split(el.dataset.chart)
        this._chartMode = { ...this._chartMode, [zone]: mode }
        this._render(true)
      })
      on('[data-gear]', 'click', (el) => {
        this._settings = el.dataset.gear
        this._render(true)
        if (this.scrollIntoView) this.scrollIntoView({ block: 'start' })
      })
      on('[data-back]', 'click', () => {
        this._settings = null
        this._render(true)
        if (this.scrollIntoView) this.scrollIntoView({ block: 'start' })
      })

      on('[data-sched-zone]', 'click', (el) => {
        this._sched = { ...this._sched, zone: el.dataset.schedZone, day: this._selected(config).day }
        this._pop = null
        this._render(true)
      })
      on('[data-sched-day]', 'click', (el) => {
        this._sched = { zone: this._selected(config).zone.id, day: el.dataset.schedDay }
        this._pop = null
        this._render(true)
      })
      on('[data-slot-add]', 'click', () => this._addSlot())
      on('[data-slot-del]', 'click', (el) => this._editSlots((slots) => slots.filter((slot) => slot.id !== el.dataset.slotDel)))
      on('[data-slot-time]', 'change', (el) => {
        if (/^\d\d:\d\d$/.test(el.value)) this._editSlot(el.dataset.slotTime, (slot) => { slot.time = el.value })
      })
      on('[data-slot-name]', 'change', (el) => this._editSlot(el.dataset.slotName, (slot) => { slot.name = el.value.trim() }))
      on('[data-slot-step]', 'click', (el) => {
        const [id, direction] = split(el.dataset.slotStep)
        this._editSlot(id, (slot) => { slot.target = clamp(Math.round((slot.target + Number(direction) * STEP) * 10) / 10) })
      })
      on('[data-slot-minutes]', 'change', (el) => {
        const minutes = Math.max(1, Math.min(1440, parseInt(el.value, 10) || 1))
        this._editSlot(el.dataset.slotMinutes, (slot) => { if (slot.motion) slot.motion.minutes = minutes })
      })
      on('[data-slot-nocond]', 'click', (el) => this._editSlot(el.dataset.slotNocond, (slot) => { slot.motion = null }))
      on('[data-slot-rooms]', 'click', (el, event) => {
        event.stopPropagation()
        this._pop = this._pop && this._pop.slot === el.dataset.slotRooms && this._pop.kind === 'rooms' ? null : { kind: 'rooms', slot: el.dataset.slotRooms }
        this._render(true)
      })
      on('[data-slot-sensors], [data-slot-addcond]', 'click', (el, event) => {
        event.stopPropagation()
        const id = el.dataset.slotSensors || el.dataset.slotAddcond
        this._pop = this._pop && this._pop.slot === id && this._pop.kind === 'sensors' ? null : { kind: 'sensors', slot: id, add: !el.dataset.slotSensors }
        this._render(true)
      })
      on('[data-pop-room]', 'change', (el) => {
        const slotId = this._pop && this._pop.slot
        const boxes = [...this.querySelectorAll('[data-pop-room]')]
        const chosen = boxes.filter((box) => box.checked).map((box) => box.dataset.popRoom)
        this._editSlot(slotId, (slot) => { slot.thermostats = chosen.length === boxes.length ? [] : chosen })
      })
      on('[data-pop-sensor]', 'change', () => {
        const slotId = this._pop && this._pop.slot
        const chosen = [...this.querySelectorAll('[data-pop-sensor]')].filter((box) => box.checked).map((box) => box.dataset.popSensor)
        this._editSlot(slotId, (slot) => {
          if (!chosen.length) slot.motion = null
          else slot.motion = { sensors: chosen, minutes: slot.motion ? slot.motion.minutes : 60 }
        })
      })

      on('[data-season-enabled]', 'change', (el) => this._service('set_heating_season', { enabled: el.checked }))
      on('[data-season]', 'change', (el) => {
        if (el.value === '') return
        this._service('set_heating_season', { [el.dataset.season]: Number(el.value) })
      })
    }
  }

  // Declared, not registered: annika-common.js registers once its helpers exist.
  ;(window.AnnikaCards ||= []).push([CARD, AnnikaHeatingCard, ['annika-ac-tiles-card']])

  window.customCards = window.customCards || []
  window.customCards.push({
    type: CARD,
    name: 'Annika Heating',
    description: 'Thermostats by zone: targets, schedule, heating season and the temperature of the day.',
  })
})()
