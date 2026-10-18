# Monitoring graph visual language

This review treats the graph as the application's real-time process model. Its
visual language must make a process understandable before it is activated and
explain the same process while it runs. A collection of draggable settings forms
would not meet that standard.

The review starts from feature head `1b5cb09` and incorporates main `73fec3c`.
The foundation is suitable for continued development after the corrections below.
Execution, presentation, reusable designs, immutable revisions, bound runs and
observation envelopes already have separate owners. Keep those boundaries.

## Corrections made in this review

| Finding | Correction |
| --- | --- |
| Canvas and keyboard connections accepted incompatible data kinds until validation. | Both use one authoring guard over the generated catalog's types, occupied inputs, cycles and resource limits. The backend compiler remains authoritative. |
| Custom titles could hide the underlying operation. | A custom title retains the operation name beneath it. Roles use text and a subtle stage color; colored connection dots expose types on hover and through accessible names. |
| Edge identity used array positions. Sparse merge order values produced misleading input numbers. | Renderer identity uses the stable endpoint pair. Inspector order and accessible connection ranks use executable order, independent of storage order. Adding an input preserves relative order and assigns bounded contiguous ordinals. |
| Role colors, wire meaning and runtime text lacked a shared grammar. | Drafts and runs share one presentation adapter, solid directional wires and data-type colors. Dots are centered on the left and right card edges. Configuration issues and sampled execution state have separate badges. |
| Repeating data types on cards and every connection interrupted the flow. | Matching colored dots replace visible input/output labels. Valid targets gain a ring during connection; unavailable targets fade. Type names appear on hover and in settings. Wires carry no visible text, and the canvas has no separate legend. Accessible descriptions retain the type and merge rank. |
| “Keep raw” implied that a passthrough could recover original readings after a transform. | The operation is named “Pass through.” Raw bypass follows an explicit branch from aligned inputs; passthrough preserves its incoming representation. |
| The zoom floor prevented a long maximum-sized chain from fitting in the canvas. | “Fit entire graph” supports the bounded V1 graph size, while “Locate selected component” restores a readable detail view. Browser checks verify both after automatic arrangement. |
| Automatic fitting made laptop and phone labels too small. | Opening and arranging use a readable working scale. Larger graphs start near the input or selected component; the explicit overview control still fits the whole graph. Saving, manual moves and diagnostic polling preserve the camera. |
| Permanent component and settings sidebars crowded the canvas. | A searchable Add component popover supports clicking and dragging. One collapsible inspector opens on selection; service settings use the same space. Mobile uses the same controls with an overlay inspector. |
| Curved connections could pass through boxes after manual moves. | Completed connections use orthogonal segments with small rounded corners, routed around all boxes. Moving an unrelated box also recalculates affected geometry. |

Unknown component contracts retain their topology for explanation, display
unavailable data types and prevent new connections. The editor must never invent
feature semantics for an unavailable component.

## The grammar

| Concept | Meaning | Visual treatment |
| --- | --- | --- |
| Component role | Input, transform, combine, detector, decision policy or evidence output | Role text, a tinted surface and a colored top border; feature processing is teal, detectors violet, policies amber and evidence slate |
| Operation | The catalog implementation and contract selected for that node | Operation name remains visible when a user supplies a custom title |
| Data kind | What crosses a boundary | Matching dot and wire colors: features teal, scores violet, P-values blue and decisions amber; all links share a solid line and arrow style |
| Connection | A directed dependency between operations | Left-to-right ports, orthogonal segments and an arrow; placement never changes execution |
| Ordered feature merge | Column concatenation for one aligned observation | Inspector ordering and accessible incoming ranks |
| Configuration issue | A problem with the current design | Issue badge linked by selection to inspector details |
| Sampled execution state | What the latest detached runtime report says about a component | A separate labeled state badge, with snapshot age and progress in diagnostics |
| Title and arrangement | Presentation of a stable node | Stored outside executable semantics; one geometry definition serves cards and automatic arrangement |

The wire vocabulary distinguishes **features**, **scores**, **P-values** and
**decisions**. Features are ordered, named numeric columns. An anomaly score is
detector-specific; it is not interchangeable with a calibrated P-value. A decision
is the policy result. Evidence is persisted by the terminal output in V1, rather
than exposed as a further routable port. Feature provenance shown for a model
describes its contributing inputs, not the shape of its score output.

Hover text, accessible names and the inspector expose type names without adding
labels to cards. During mouse dragging or two-tap connection, a ring marks valid
targets and incompatible or occupied inputs fade. These hints use the same
authoring guard as the inspector, including cycle and resource limits.
Dots have a 28px interaction area around their 16px visible circle.
Every connection uses the same
solid line, width and arrow style; data kinds change only its color. Runtime state
uses its own labeled badge, so an invalid draft, an initializing model and a
failed execution do not become the same red node. Wires do not animate imaginary
messages. A sampled badge cannot establish current liveness; snapshot age,
coverage and persistence freshness remain explicit in the existing diagnostics.
Component selection and **Locate selected component** provide a readable detail
view of a larger graph; **Fit entire graph** restores its overview. Keyboard and
narrow-screen navigation use the same component identities and inspector.
Node titles are 16px at the default working scale. Descriptions live in component
settings. The percentage control returns an overview or manually zoomed canvas
to readable size. Panels start closed; closing settings restores canvas width
without discarding edits or moving nodes.

`routing.ts` adapts the pinned MIT React Flow Smart Edge library to the shared
card geometry. It checks returned paths against every box and preserves port
entry/exit directions. Clear aligned connections stay straight; other routes
use 90-degree bends with 5px corner rounding and 8px box clearance. The canvas
memoizes geometry independently of selection and runtime diagnostics. Routing
allocations are bounded for sparse saved coordinates. Bends remain derived
presentation data and are never saved in the executable definition or layout.
Measured node dimensions remain renderer state across data projections so
React Flow retains port bounds during connection hints and live refreshes.
If overlapping boxes physically block a port, dashed end stubs and a short
spacing hint keep the connection identifiable; moving the boxes apart restores
its complete route. The draft remains available for inspection and editing.

Keep the main canvas readable as a continuous process: a component explains its
operation, a port explains its contract, and a link shows the dependency. Do not
repeat the same data label along every wire or add a legend to explain decorative
symbols. Selection exposes parameters, ordered inputs, feature lineage and live
values in the inspector. More expressive operations should add meaningful typed
capabilities through the catalog, rather than require more permanent annotations
on every connection. A saved layout is for arrangement; it never substitutes for
explicit execution semantics.

## Boundaries that keep this extensible

The persisted Pydantic definition remains the sole execution language. React Flow
is a renderer and interaction surface; `graphPresentation.ts` projects the
definition into it without changing the definition. Component types and parameter
descriptors come from the shared catalog. `semantics.ts` owns the presentation
vocabulary. The canvas, inspector and toolbox share their authoring rules instead
of developing competing interpretations.

V1 intentionally executes one aligned input observation, a feature DAG, one
detector, one policy and one evidence output. Its singleton and input-arity rules
are an explicit current execution profile, enforced by the compiler and mirrored
by the editor's advisory guard. They are not a promise that the execution engine
already supports every graph the renderer could draw.

A new operation that fits this profile should enter through the existing typed
catalog, parameter descriptors, compiler, numerical adapter and tests. A new
execution shape requires a reviewed versioned contract and corresponding runtime
support. In particular, multiple named ports would need stable port identities
and a migration from V1's endpoint pairs; array indices and visual positions must
never acquire that meaning.

Future extensions must define their data semantics, observation/time alignment,
state ownership, readiness, learning/scoring order and recovery behavior before
becoming connectable. Several float-valued model outputs do not become comparable
merely because a wire can connect them. Calibration and provenance need explicit
meaning. Feature concatenation must keep its existing same-observation semantics.
These are admission criteria for a future change, not a plan to implement one now.

The numerical boundary stays equally focused: Aberrant's graph remains a
standalone feature DAG with one terminal model. OFF-KEY owns bindings, strategy
lifecycle, policy, persistence and the visual language. A future application
execution shape must not silently weaken that numerical API or add application
infrastructure to Aberrant.

## Inspiration and verification

[Node-RED's node guide](https://nodered.org/docs/user-guide/editor/workspace/nodes)
separates port labels, configuration errors and runtime status. The
[Node-RED wire guide](https://nodered.org/docs/user-guide/editor/workspace/wires)
also treats links as direct connections between ports. The
[Blender node guide](https://docs.blender.org/manual/en/latest/interface/controls/nodes/parts.html)
locates data contracts at sockets, while
[n8n's connection guide](https://docs.n8n.io/build/understand-workflows/workflow-components/connect-nodes-together)
describes the output-to-input link as data routing. These support keeping the
continuous path visually quiet and exposing detail at its components. The
[KNIME workflow guide](https://docs.knime.com/ap/5.8/analytics_platform_user_guide/)
uses typed ports and distinguishes configured/executed state. These support the
separation used here; their message and batch execution models are not adopted.
[React Flow's handle guide](https://reactflow.dev/learn/customization/handles)
supports explicit handle identity. The V1 adapter uses stable input/output handles
while preserving the existing persisted graph contract.

Regression checks cover incompatible connections, cycles, sparse merge order,
stable edge identity, unknown contracts, retained operation identity and the
score/P-value distinction. Real production browser journeys cover both strategies,
keyboard authoring, custom titles, directional ports, actual backend validation,
reload, dark mode and narrow screens. Existing maximum-graph, live monitoring,
replacement, persistence and software rollback gates remain required.
