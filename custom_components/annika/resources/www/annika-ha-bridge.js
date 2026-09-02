// Annika <-> Home Assistant readiness bridge.
//
// Installed automatically by the `annika` integration (see
// custom_components/annika/__init__.py) — served as a static path and
// injected into every dashboard via `add_extra_js_url`. No manual copy to
// `config/www/` or Settings > Dashboards > Resources entry needed.
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
  // the parent app, not a separate, freely-draggable surface. Two things fight
  // that, both native to *this* document (Annika's parent page has no way to
  // reach in and fix either from the outside, since this is a separate,
  // cross-origin document — has to happen from in here):
  //  - the elastic "rubber-band" bounce at the edges of a scroll/trackpad
  //    gesture, even when there's nothing to actually scroll;
  //  - some dashboard content ending up very slightly wider than the phone's
  //    own viewport (a card, a table, whatever), which turns the whole page
  //    sideways-scrollable/draggable instead of just clipping the excess.
  // Both are fixed the same blunt, safe way: nothing in a HA dashboard needs
  // page-level horizontal scroll — individual cards can still scroll
  // themselves horizontally if they already do, this only clips the root.
  function suppressOverscrollAndOverflow() {
    try {
      var style = document.createElement('style')
      style.setAttribute('data-annika-bridge', '')
      // `100%` here, not `100vw`: `vw` is defined against the *layout*
      // viewport, which on mobile Safari can measure wider than what's
      // actually visible inside an iframe (browser-chrome allowances that
      // don't apply to embedded content at all). That mismatch is exactly
      // what caused dashboard headers/cards to appear clipped on one edge —
      // this box was being told it could be wider than the iframe truly is,
      // then got position/overflow-clipped down to the real size. `100%`
      // resolves against the iframe's own actual rendered box, no viewport
      // unit ambiguity involved.
      style.textContent = 'html, body { overscroll-behavior: none !important; overflow-x: hidden !important; max-width: 100% !important; }'
      ;(document.head || document.documentElement).appendChild(style)
    } catch (err) {
      // Best effort — if this fails, HA just keeps its native behavior.
    }
  }
  suppressOverscrollAndOverflow()

  function post(type, distance) {
    try {
      var payload = { source: SOURCE, type: type }
      if (typeof distance === 'number') payload.distance = distance
      window.parent.postMessage(payload, TARGET_ORIGIN)
    } catch (err) {
      // Embedding context rejected the message (unexpected origin, etc). Nothing
      // to recover from here; the parent will simply fall back to its own
      // tunnel-health-based gate.
    }
  }

  // Lets lib/use-unit-frame.ts in the client repo remember which dashboard/
  // view was on screen, so a reconnect (pull-to-refresh, a dropped tunnel, a
  // plain reload) can request a fresh ticket that lands back on the same
  // place instead of HA's default page. Only sent when the path actually
  // changed, piggybacked on the same ~2s cadence as the `tick()` readiness
  // poll below rather than its own listeners — navigating dashboards doesn't
  // need to be reported faster than that.
  //
  // Deliberately `location.pathname` ONLY, never `location.search`: the
  // gateway's ticket middleware never strips `?ticket=...` from the URL bar
  // once it's been consumed (see the comment on `suppressOverscrollAndOverflow`
  // era history in the backend's annika-gateway service — it's a dangling,
  // harmless param by design, to dodge a service-worker redirect bug), so
  // `location.search` here would always still have the *previous* ticket
  // baked into it. Reporting that back as the "path" and having the next
  // reconnect glue a *second* `?ticket=...` onto it is exactly the bug that
  // broke this the first time around — keep it to the path only.
  var lastPath = null
  function postPath() {
    var current = location.pathname
    if (current === lastPath) return
    lastPath = current
    try {
      window.parent.postMessage({ source: SOURCE, type: 'path', path: current }, TARGET_ORIGIN)
    } catch (err) {
      // Same best-effort as post() above.
    }
  }

  // Relays a downward pull-from-top gesture to components/pull-to-refresh.tsx
  // in the parent, which already understands 'annika-pull-move'/'-end' — it
  // just never had anything inside HA's own iframe sending them. Pure
  // event-driven touch listeners, no polling: negligible cost while idle. The
  // parent owns the actual refresh threshold; MAX_PULL/RESISTANCE here only
  // need to roughly match components/pull-to-refresh.tsx's own constants so
  // the visual "pull" feels the same whether it starts on HA or outside it.
  var MAX_PULL = 110
  var RESISTANCE = 0.5
  var pullArmed = false
  var pullStartY = null

  // HA's dashboard is built from web components with their own Shadow DOM, so
  // the element that's actually scrolling when you're mid-dashboard is nested
  // inside one or more shadow roots — checking only the root document's
  // scrollTop (as if this were a plain page) is always 0 and never reflects
  // where the *view* itself is really scrolled to. `composedPath()` gives the
  // real innermost-to-outermost chain for the touch, piercing shadow
  // boundaries, so walk that to find whichever element is actually scrolled.
  function isAtScrollTop(event) {
    var path = (event.composedPath && event.composedPath()) || [event.target]
    for (var i = 0; i < path.length; i++) {
      var el = path[i]
      if (!(el instanceof Element)) continue
      var style = getComputedStyle(el)
      var scrollable = /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight
      if (scrollable) return el.scrollTop <= 0
    }
    var scroller = document.scrollingElement || document.documentElement
    return scroller.scrollTop <= 0
  }

  document.addEventListener(
    'touchstart',
    function (event) {
      if (event.touches.length !== 1) return
      pullArmed = isAtScrollTop(event)
      pullStartY = event.touches[0].clientY
    },
    { passive: true }
  )

  document.addEventListener(
    'touchmove',
    function (event) {
      if (!pullArmed || pullStartY === null) return
      var delta = event.touches[0].clientY - pullStartY

      if (delta <= 0) {
        pullArmed = false
        post('annika-pull-move', 0)
        return
      }

      post('annika-pull-move', Math.min(delta * RESISTANCE, MAX_PULL))
      if (event.cancelable) event.preventDefault()
    },
    { passive: false }
  )

  function onPullEnd() {
    if (!pullArmed) return
    pullArmed = false
    pullStartY = null
    post('annika-pull-end')
  }
  document.addEventListener('touchend', onPullEnd, { passive: true })
  document.addEventListener('touchcancel', onPullEnd, { passive: true })

  // ---------------------------------------------------------------------
  // Who is using the app.
  //
  // Every household member reaches this Home Assistant through the Annika
  // app, and the app signs them all in with one shared HA user — so HA's own
  // `context.user_id` says the same thing no matter who pressed the button.
  // The parent app is the only place that knows the difference, so it sends
  // the name down here, and this stamps it onto each service call as it goes
  // out. See custom_components/annika/actor.py for the other half.
  //
  // Nothing about this is a permission check: the name is asserted, not
  // proven, and HA records it as `actor_verified: false`. It exists so a
  // notification can say who disarmed the alarma, and for nothing else.
  // ---------------------------------------------------------------------

  var actor = null

  function readActor(value) {
    if (!value || typeof value !== 'object') return null
    var name = typeof value.name === 'string' ? value.name.trim() : ''
    if (!name) return null
    return { name: name.slice(0, 64), id: typeof value.id === 'string' ? value.id : null }
  }

  window.addEventListener('message', function (event) {
    // The only origin allowed to say who is acting. Without this check any
    // page that got itself embedded around this one could name anybody.
    if (event.origin !== TARGET_ORIGIN) return
    var data = event.data
    if (!data || typeof data !== 'object' || data.source !== 'annika-app') return
    if (data.type !== 'actor') return
    // An explicit null is the app saying it no longer knows who is there
    // (signed out, session expired) — honored, so actions stop being
    // attributed rather than keeping the last name around.
    actor = readActor(data.actor)
  })

  // Collects what the call is about, in whichever shape
  // home-assistant-js-websocket put it in — `target.entity_id` since the
  // services rewrite, `service_data.entity_id` before it, either a string or
  // a list. HA matches the stamp to the call on these, so a miss here means
  // the action simply arrives unattributed.
  function callEntityIds(message) {
    var found = []
    var sources = [message.target, message.service_data]
    for (var i = 0; i < sources.length; i++) {
      var source = sources[i]
      if (!source || typeof source !== 'object') continue
      var value = source.entity_id
      if (typeof value === 'string') found.push(value)
      else if (Array.isArray(value)) {
        for (var j = 0; j < value.length; j++) {
          if (typeof value[j] === 'string') found.push(value[j])
        }
      }
    }
    return found.filter(function (id, index) {
      return found.indexOf(id) === index
    })
  }

  // Every service call the frontend makes — a tile, a more-info dialog, a
  // dashboard button — goes out through `sendMessagePromise`, so wrapping it
  // once catches all of them without this script needing to know a single
  // thing about any particular card.
  //
  // The stamp is sent but deliberately NOT awaited. `annika/stamp_actor` is a
  // synchronous websocket command, so Home Assistant has fully processed it
  // before it reads the call that follows on the same socket — awaiting would
  // buy no extra ordering and would put a full tunnel round trip in front of
  // every button press.
  function wrapConnection(connection) {
    if (connection.__annikaActorWrapped) return
    connection.__annikaActorWrapped = true

    var original = connection.sendMessagePromise.bind(connection)

    connection.sendMessagePromise = function (message) {
      try {
        if (
          actor &&
          message &&
          message.type === 'call_service' &&
          // Annika's own services are plumbing rather than something a person
          // did, and stamping the stamp would be a loop.
          message.domain !== 'annika'
        ) {
          original({
            type: 'annika/stamp_actor',
            name: actor.name,
            id: actor.id,
            domain: message.domain,
            service: message.service,
            entity_id: callEntityIds(message),
          }).catch(function () {
            // An older unit without this command answers with an error. The
            // call itself still goes through below, just unattributed — the
            // attribution is never allowed to be the reason something the
            // user pressed does not happen.
          })
        }
      } catch (err) {
        // Same rule: fail open, always.
      }

      return original.apply(null, arguments)
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

  // Some Lovelace cards (confirmed on the camera dashboard's snapshot
  // filmstrip — it renders scrolled to show a sliver of the *previous* image
  // instead of the latest one) compute a one-time layout/scroll measurement
  // against the iframe's box size. That measurement can run before this
  // *particular* embedding has settled to its final size — plain <img>/CSS
  // width isn't the same signal a card's own JS measures off of, and nothing
  // here can reach into that card's internals directly (HA is a stock,
  // unmodified app; no card-specific hooks to call). A `resize` event is the
  // generic, low-risk nudge: any HA component that reacts to viewport size at
  // all re-runs its own measurement against the now-stable layout, without
  // this script needing to know which card or how. Fired once, shortly after
  // the first sign HA itself is fully loaded, not on every tick — cheap
  // safety margin, not a recurring disruption to scroll position elsewhere.
  var resizeNudged = false
  function nudgeResizeOnce() {
    if (resizeNudged) return
    resizeNudged = true
    setTimeout(function () {
      try {
        window.dispatchEvent(new Event('resize'))
      } catch (err) {
        // Best effort.
      }
    }, 300)
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
        wrapConnection(hass.connection)
      }
      // `hass` only exists once HA has authenticated *and* pulled its initial
      // state dump — this is the same moment the stock "Loading data" screen
      // disappears. Report it, then keep watching at a relaxed pace in case
      // HA ever swaps the connection object out from under us.
      post('ready')
      postPath()
      if (!actor) post('actor-request')
      nudgeResizeOnce()
      setTimeout(tick, 2000)
      return
    }

    if (attempts < MAX_ATTEMPTS) setTimeout(tick, POLL_MS)
  }

  tick()
})()
