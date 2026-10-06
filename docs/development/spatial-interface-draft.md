# Spatial interface draft

Run `npm ci` and `npm run dev` in `frontend`, then open
`http://localhost:5173/spatial-lab`. This route is available only in Vite development
mode. It does not replace the landing page or authenticated dashboard.

The draft uses React, Three.js with OrbitControls, the existing ECharts wrapper,
Radix Dialog for keyboard focus management, and a lazily loaded MQTT.js client.
It needs no backend and writes no telemetry to a server.

## Interaction

- Inspect objects by clicking geometry, scene labels, or the searchable object list.
  The inspector shows a bounded line chart, observed message rate, count, and freshness.
- Drag empty space to pan, right-drag to orbit, and scroll to zoom. The toolbar offers
  top view, fit, and named perspectives. Touch supports pan and two-finger zoom/orbit.
- Enable Arrange to drag objects or collection tiles on the ground plane. Movement
  snaps to quarter units. Arrow keys move selected objects; Shift increases the step.
- Pin individual objects or lock a collection. Group movement and automatic placement
  preserve pinned objects. Undo/redo applies to layout edits; camera navigation is separate.
- Collections have user-selected names and colours. Membership is visual organization;
  moving a sensor into a collection does not change its broker connection.
- Collapse a collection to an aggregate object. Cross-collection links survive;
  internal links are hidden. The collection inspector reports aggregate stream arrivals.
- Camera, positions, groups, locks, and perspectives save in browser storage, separated
  by local user, source, and scale experiment. This preserves preferences across reloads
  and sign-ins in the same browser; it does not implement account or cross-device sync.
  Export/import moves validated presentation state only. Telemetry is never exported.

## Data and limits

The default is an explicitly labelled simulator. Its cadence control changes actual
simulated arrivals, including quiet streams at zero. Histories use fixed 360-sample
buffers and are lost when the runtime ends; this is a sample limit, not an hours-long
retention promise. Chart inspection preserves its selected time range until returning
to the live range.

The optional public feed uses Helsinki Region Transport's documented HFP MQTT service
at `wss://mqtt.hsl.fi:443/`, subscribing to tram VP messages. The first 24 observed
vehicles become stable objects. Speed is displayed in km/h; geographic positions are
not used or persisted. Invalid payloads are ignored and retained deliveries do not
produce current-arrival pulses. Credit: [HSL open data](https://www.hsl.fi/en/opendata),
CC BY 4.0. Live availability depends on the public broker and the client network;
connection failure remains visible and does not silently substitute simulated data.

Detection evidence, private application sources, editing broker configuration, and
team-shared layouts are deliberately outside this first interactive prototype.

## Performance

Broker and sensor geometry is instanced; links and pulses are batched. Scene labels
are bounded, and the object list renders at most 40 entries with search across all
objects. Layout interpolation updates link endpoints together with their objects.
Telemetry runs outside React; inspector readings refresh once per second.

Balanced mode caps pixel ratio at 1.5 and visual arrivals at 80 per second. Economy
caps pixel ratio at 1, frame rate at 30, and visual arrivals at 30 per second. A share
of the visual budget is reserved for the inspected connection at high load. Visual
sampling never changes telemetry counts. Hidden tabs suspend rendering and collection;
reduced-motion preferences suppress travelling pulses. WebGL failure leaves the
searchable inspector usable.

The live HUD reports recent rendering fps, draw calls, visible objects, and pulses.
Use the 18, 250, and 1,000-stream scale experiments to assess the actual browser and
hardware. Unit tests cover layout validation, locking, collapse relationships, bounded
telemetry, MQTT lifecycle, geometry updates, and pulse budgets. Device/GPU coverage
and production load testing remain follow-up work before making this a default UI.
