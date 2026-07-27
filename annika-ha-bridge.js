// Annika <-> Home Assistant readiness bridge.
//
// Manual install per unit (no automated provisioning — this repo's files are
// hand-copied into a unit's HA config, same as annika-theme.yaml):
//
//   1. Copy this file to the unit's `config/www/annika-ha-bridge.js`
//      (Home Assistant serves anything under `config/www/` at `/local/...`).
//   2. Settings > Dashboards > ⋮ (top-right) > Resources > Add resource.
//      URL: `/local/annika-ha-bridge.js`   Resource type: JavaScript module
//   3. Refresh the dashboard once so HA picks up the new resource.
//
// Home Assistant is a stock, unmodified, cross-origin app — the Annika client
// (app.annikagroup.com, embedding this unit's HA in an iframe) can't see into
// its DOM or know when its own "Loading data" screen has resolved, or when its
// websocket connection drops/recovers. This script runs *inside* HA's own
// frontend instead, and reports the real state to the parent via postMessage.
// If it's ever opened directly (not embedded in Annika's iframe), or the
// message gets rejected for any reason, this is a silent no-op — it never
// touches or interferes with HA itself.
//
// This deliberately doesn't replace the tunnel-reachability check the Annika
// backend already does (backend -> gateway -> rathole -> HA): that catches
// "the tunnel is down". This catches the layer above it: "the tunnel is up,
// but HA's own frontend hasn't finished its initial data sync yet, or its
// websocket just dropped/reconnected in place." See app/lib/use-unit-frame.ts
// in the client repo for how these two signals are combined.
;(() => {
  if (window.top === window.self) return // not embedded, nothing to report

  var TARGET_ORIGIN = 'https://app.annikagroup.com'
  var SOURCE = 'annika-ha-bridge'
  var POLL_MS = 250
  var MAX_ATTEMPTS = 400 // ~100s ceiling looking for the root element/hass

  // Embedded in Annika's iframe, HA's own page is meant to feel like part of
  // the parent app, not a separate, freely-draggable surface. But the elastic
  // "rubber-band" bounce at the edges of a scroll/trackpad gesture is native
  // browser behavior applied to *this* document — Annika's parent page has no
  // way to reach in and turn it off from the outside, since this is a
  // separate, cross-origin document. Turn it off from in here instead, as
  // early as possible so there's no window where it's still visible.
  function suppressOverscrollBounce() {
    try {
      var style = document.createElement('style')
      style.setAttribute('data-annika-bridge', '')
      style.textContent = 'html, body { overscroll-behavior: none !important; }'
      ;(document.head || document.documentElement).appendChild(style)
    } catch (err) {
      // Best effort — if this fails, HA just keeps its native bounce.
    }
  }
  suppressOverscrollBounce()

  function post(type) {
    try {
      window.parent.postMessage({ source: SOURCE, type: type }, TARGET_ORIGIN)
    } catch (err) {
      // Embedding context rejected the message (unexpected origin, etc). Nothing
      // to recover from here; the parent will simply fall back to its own
      // tunnel-health-based gate.
    }
  }

  function attachConnectionListeners(connection) {
    if (connection.__annikaBridgeAttached) return
    connection.__annikaBridgeAttached = true
    // See https://github.com/home-assistant/home-assistant-js-websocket —
    // `Connection` fires 'ready' once auth + initial sync completes (including
    // after a reconnect), and 'disconnected' the moment the socket drops.
    connection.addEventListener('ready', function () {
      post('ready')
    })
    connection.addEventListener('disconnected', function () {
      post('disconnected')
    })
  }

  var attempts = 0
  var lastConnection = null

  function tick() {
    attempts += 1

    var root = document.querySelector('home-assistant')
    var hass = root && root.hass

    if (hass && hass.connection) {
      if (hass.connection !== lastConnection) {
        lastConnection = hass.connection
        attachConnectionListeners(hass.connection)
      }
      // `hass` only exists once HA has authenticated *and* pulled its initial
      // state dump — this is the same moment the stock "Loading data" screen
      // disappears. Report it, then keep watching at a relaxed pace in case
      // HA ever swaps the connection object out from under us.
      post('ready')
      setTimeout(tick, 2000)
      return
    }

    if (attempts < MAX_ATTEMPTS) setTimeout(tick, POLL_MS)
  }

  tick()
})()
