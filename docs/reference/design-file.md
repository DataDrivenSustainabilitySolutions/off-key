# Design file

A monitoring design travels as one JSON document. The composer downloads it and
opens it, and a script or an agent can write one. It holds what a saved
template holds, which is also the body of `POST /pipelines`: a name, a
description, the definition of the steps and the layout of their cards.

## When to use this page

Use this page when keeping designs under version control, moving a design
between installations, or writing a design outside the composer.

## The document

| Key | Required | Meaning |
| --- | --- | --- |
| `format` | Yes | Always `aberration-design`. It tells a design from any other JSON file. |
| `schema_version` | No | Version of this format, `1`. |
| `$schema` | No | Where the schema is published. Editors use it to check and complete the file. |
| `name` | No | Name of the design, up to 120 characters. A file without one is named after the file. |
| `description` | No | When to use the design, up to 2000 characters. |
| `definition` | Yes | The steps (`nodes`), the connections between them (`edges`), the readings the design takes in (`input_slots`) and its `settings`. |
| `layout` | No | Where each card stands, by the step's id, the title it carries, what a switched-off step was, and the notes on the canvas. |

The definition is read strictly: a key the schema does not name is refused, so
a misspelt setting is reported instead of being ignored.

## Example

```json
{
  "$schema": "https://docs.aberration.app/reference/design-file.schema.json",
  "format": "aberration-design",
  "schema_version": 1,
  "name": "Charger current",
  "description": "Smooths the current of a charger and scores how unusual it is.",
  "definition": {
    "schema_version": 2,
    "input_slots": [{ "id": "current", "label": "Current", "unit": "A" }],
    "nodes": [
      { "id": "input", "kind": "source", "component": "source.aligned" },
      { "id": "smooth", "kind": "transform", "component": "prepare.smooth", "params": { "window_size": 10 } },
      { "id": "detector", "kind": "detector", "component": "detector:aberrant_online_isolation_forest" },
      { "id": "calibrate", "kind": "calibration", "component": "calibrate.fixed_split" },
      { "id": "policy", "kind": "policy", "component": "policy.quantile" },
      { "id": "output", "kind": "output", "component": "output.evidence" }
    ],
    "edges": [
      { "source": "input", "target": "smooth" },
      { "source": "smooth", "target": "detector" },
      { "source": "detector", "target": "calibrate" },
      { "source": "calibrate", "target": "policy" },
      { "source": "policy", "target": "output" }
    ]
  },
  "layout": {
    "nodes": {
      "input": { "x": 0, "y": 96 },
      "smooth": { "x": 288, "y": 96, "label": "Calm the noise" },
      "detector": { "x": 576, "y": 96 },
      "calibrate": { "x": 864, "y": 96 },
      "policy": { "x": 1152, "y": 96 },
      "output": { "x": 1440, "y": 96 }
    }
  }
}
```

## Writing a design

- **Form.** The definition says `"schema_version": 2`. The composer opens no
  other form.
- **Steps.** Each node names a `component` from the catalog and has the
  component's `kind`. `GET /pipeline-components` lists every component with its
  kind, what it takes in and gives out, and its settings; a step's `params` are
  named as those settings are, and a setting left out takes its default.
- **Connections.** An edge leads from the `source` step to the `target` step.
  `order` places it among the inputs of a step that takes several, such as
  **Merge features**.
- **Readings.** `input_slots` names the readings the design takes in. A file
  holds no readings of a real device: the service that runs the design maps a
  reading to each slot.
- **Layout.** `layout` may be left out, in whole or for some steps. The
  composer then arranges the whole design when it opens the file. To title a
  step without placing it, give the node itself a `label`.
- **Notes.** `layout.notes` lists notes on the canvas, each with an `id` of
  its own, a place (`x`, `y`) and a `text` of up to 2000 characters. A note
  says why the design is built the way it is, for example
  `{ "id": "note_1", "x": 288, "y": 0, "text": "Smooth first: the sensor is noisy." }`.
  It has no effect on what the design computes.
- **Switched-off steps.** A step that is switched off in the composer is
  written as a `features.passthrough` step, so the file runs as it reads.
  `layout.switched_off` keeps, by the step's id, the `component` and `params`
  the step had, and the composer switches it on again from there. A file
  written by hand has no need of it.

A file can be opened while the design is unfinished. `POST /pipelines/validate`
with the `definition` answers what the composer shows: whether the design can
run, and what is left to do at which step.

## Schema

[design-file.schema.json](design-file.schema.json) is the JSON Schema of the
document, in the 2020-12 draft. It is generated from the model the API reads
(`PipelineDesignFile` in `off_key_core.schemas.pipelines`) by
`backend/scripts/generate_pipeline_types.py`, and CI fails when the published
file differs from the model.

The schema describes the shape of the document. Whether the steps fit together
is the compiler's answer, and which settings a step has is the catalog's.

## In the composer

**Save template** opens a dialog whose **Download as a file** saves the design
under the name and description entered there, as `<name>.design.json`. **Load
template** has **Open a file…**, and a file dropped on the canvas is opened the
same way. The opened design takes the place of the one on the canvas, and
**Undo** brings that one back. See
[Visual monitoring pipelines](../user-guide/monitoring.md#visual-monitoring-pipelines).
