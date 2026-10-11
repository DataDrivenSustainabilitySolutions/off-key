# Spatial interface draft

These are historical notes for the original 3D experiment. The current branch
uses the [monitoring workspace](system-explorer.md) as its application home instead;
`/spatial-lab` and `/explorer` redirect to `/` in development and production builds.

Run `npm ci` and `npm run dev` in `frontend`, then open
`http://127.0.0.1:5173/`. For a compiled frontend
with the full local backend, use the [local deployment workflow](local-deployment.md).
The local integration checkout is `.tmp/spatial-interface-draft`; its
Docker runtime and restart instructions are in `.tmp/spatial-runtime` in the
parent repository. Both directories survive a machine restart.

The draft uses React, Three.js with OrbitControls, the existing ECharts wrapper,
Radix Dialog, and a lazily loaded MQTT.js client. It adds no dependencies.

## Saved system

The default view loads a domain-agnostic definition from `GET /v1/system`.
Connections describe MQTT endpoints; devices provide optional hierarchy and
association; streams bind a concrete topic and optional JSON Pointer to a
connection and optional device. Groups organize objects independently of stream
routing. Devices can have any kind, such as a weather station or energy meter.
Names, hosts, topics, units, value types, policies, hierarchy, group membership,
and group colours belong to the saved configuration.

Signed-in administrators can add, edit, move, or remove these definitions in the
inspector. Clicking a title changes it into an editor. Enter or clicking elsewhere
saves; Escape cancels. Removing an object previews dependent definitions that
would also be removed. Moving a device to another connection explicitly shows
that its streams will follow; direct stream edits permit separate bindings.
Moving a member between groups updates both groups in one save.

`PUT /v1/system` uses `{expected_revision, document}`. A successful save returns the
canonical document; stale editors cannot overwrite a newer revision. Conflicts
refresh the saved definition while retaining the unsaved draft for review.
Configuration and audit revisions persist in additive PostgreSQL tables.
Normal members can inspect and export; administrators can edit.

The existing AmbiBox catalog is an adapter into this format, preserving its
stable IDs and exact 31 connections, 31 devices, and 714 stream definitions.
When no generic definition exists, GET derives one without modifying the legacy
catalog. The first explicit save creates the generic configuration. Subsequent
edits are independent of the charging-specific catalog and dashboard. There is
no hardcoded catalog-load step in the normal interface.

The private local preset is available at
`infra/stack/state/prod/ambibox-development-catalog.json` in the project checkout.
It is explicitly Git-ignored and has owner-only permissions (`0600`). To reuse it,
sign in to the local spatial lab, open Workspace preferences, choose Import
configuration, select this file, review the counts, and choose Replace saved
definition. Import preserves its stable IDs and does not start collection. The
file is local only; a fresh clone needs a copy from your private backup. Export
configuration after editing to keep an updated reusable definition.

Saving an endpoint or collection policy does **not** activate ingestion. Choose
Connect live to subscribe to the saved generic MQTT definitions. The inspector
shows actual typed values, receipt counts, rates, connection failures, and bounded
charts. Visual pulses sample fresh arrivals; retained MQTT deliveries do not create
pulses or inflate fresh counts. Existing persistent collection remains managed
separately.

Generic live preview uses temporary owner-bound leases, exact broker allowlists,
and private credential references. It writes no telemetry history to the database.
Changing the saved revision disconnects the current preview; reconnect after the
edit. See [local deployment](local-deployment.md) for the workshop MQTT fixture,
credentials, and start/rebuild workflow.

## Files and saved views

Export configuration writes `aberration-system` schema version 1 JSON containing
all saved definitions and stable identities. Export workspace writes
`aberration-workspace` schema version 1, adding spatial presentation state. Export
rereads the database so recently saved names travel with the file. Credentials
are references, never embedded secret values. Telemetry is not exported.

Import accepts a generic definition, a workspace bundle, or a legacy catalog.
It validates references, cycles, types, MQTT topics, payload pointers, IDs, size
limits, and group membership before displaying a replacement preview. Importing
a workspace applies its view preferences only after the database acknowledges the save.
An imported credential reference must be configured on the destination runtime;
import itself starts no broker connection.

Camera, personal groups, and named perspectives save in
browser storage by signed-in account. They survive reload and sign-in on that
browser. Workspace files transfer them to another browser. Configuration owns
catalog names, colours, and membership. Positions derive automatically from the
catalog structure. Legacy positions and locks are ignored when loading or
importing workspaces; an old manual view is fitted once to the automatic layout.

The generic overview shows brokers and entities. Selecting either opens its
searchable topic browser, distinguishing unique MQTT topics from extracted
readings. Topic and JSON-field pages are bounded, and every definition remains
reachable through search, categories, and pagination. Selecting a reading reveals
only that measurement in the scene and opens its chart. Entity links represent all actual source brokers, including
entities receiving readings through multiple brokers. Fresh arrivals blink at
the visible entity or reading; they never travel through unrelated devices.

My groups is an optional personal overlay with multiple memberships, custom
colours, inline names, and one-click filtering. It never changes catalog groups,
entity ownership, topics, or MQTT bindings. Source brokers remain visible as
context when filtering. These groups are browser/account scoped and included in
workspace exports; configuration-only exports contain only catalog structure.

All workspaces use automatic layout. Personal groups add filters and colours;
opening one fits the view. Camera navigation stays independent of object layout.
There are no manual object movement, pinning, arrangement, or layout undo controls.

Inspect objects through the scene or searchable list.
Pan on empty space, right-drag to orbit, and scroll to zoom. The toolbar offers
top view, fit, and preferences. Named perspectives capture camera
and view mode. Small screens use an inspector overlay.

## Telemetry previews

Preferences retain the optional simulator and public MQTT preview. The simulator
is explicitly labelled; its cadence control changes actual simulated arrivals,
including quiet streams at zero. Histories use fixed 360-sample buffers and are
lost when the runtime ends. This is a sample limit, not an hours-long retention
promise. Inspector charts preserve the selected time range until returning live.

The public feed uses Helsinki Region Transport's documented HFP MQTT service at
`wss://mqtt.hsl.fi:443/`, subscribing to tram VP messages. The first 24 observed
vehicles become stable objects. Speed is displayed in km/h; geographic positions
are not used or persisted. Invalid payloads are ignored; retained deliveries do
not produce current-arrival pulses. Credit: [HSL open data](https://www.hsl.fi/en/opendata),
CC BY 4.0. Connection failure stays visible without silently substituting data.

## Performance and validation

The ground is a procedural, world-anchored grid drawn with one screen-filling
quad. It has no tile boundary when panning, orbiting, or zooming. Grid lines fade
softly into the matching background and become less detailed when zoomed out.
It follows the camera through uniforms; it adds no growing geometry or idle
animation loop.

Geometry is instanced; links and pulses are batched. Labels avoid overlap and
are bounded; long names retain their start. The list renders at most 40 results,
searching every object and showing owner context for repeated stream names.
Camera and perspective changes keep scene topology references stable instead
of rebuilding catalog geometry after navigation.
Layout interpolation moves link endpoints with objects. Telemetry runs outside
React; readings refresh once per second. The configured scene renders on demand
while idle. Hidden tabs suspend rendering and preview collection.

Balanced mode caps pixel ratio at 1.5 and visual arrivals at 80 per second.
Economy caps pixel ratio at 1, frame rate at 30, and visual arrivals at 30 per
second. Visual sampling does not alter counts; reduced motion suppresses pulses.
The HUD reports actual draw calls, objects, and pulses. WebGL failure leaves the
searchable inspector usable. Scale experiments remain in telemetry previews.

Configuration is bounded to 1 MiB, 128 connections, 2,048 devices, 4,096 streams,
and 128 groups. Tests cover persistence, permissions, conflict handling, adapter
identity, validation, structure editing, imports, layout preservation, safe object
IDs, renderer batching, MQTT lifecycle, and pulse budgets. Hardware/GPU coverage
and production load testing remain necessary before making this the default UI.
