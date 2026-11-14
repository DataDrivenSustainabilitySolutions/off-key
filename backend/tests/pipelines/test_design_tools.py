"""Finding a component by its purpose, and changing a design in small edits."""

import pytest
from off_key_core.models.pipeline_edits import (
    CARD_WIDTH,
    GAP_X,
    EditError,
    edit_design,
)
from off_key_core.models.pipeline_search import search_components
from off_key_core.models.pipelines import pipeline_catalog, pipeline_catalog_id
from off_key_core.schemas.pipeline_tools import (
    ComponentSearchQuery,
    DesignEditRequest,
)
from off_key_core.schemas.pipelines import PipelineLayout
from pydantic import ValidationError

from tests.support.pipelines import template

COLUMN = CARD_WIDTH + GAP_X


def found(query="", **filters):
    return search_components(ComponentSearchQuery(query=query, **filters))


def ids(page):
    return [component.id for component in page.components]


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("calm noise", "prepare.smooth"),
        ("smoothing", "prepare.smooth"),
        ("remove spikes", "prepare.despike"),
        ("running total", "prepare.accumulate"),
        ("alarm when evidence builds up", "policy.martingale"),
        ("isolation forest", "detector:pyod_iforest"),
        ("Skip observations outside a range", "prepare.range"),
    ],
)
def test_search_finds_a_step_by_what_it_is_for(query, first):
    assert ids(found(query))[0] == first


def test_search_answers_in_a_few_lines_per_component():
    page = found("calm noise")
    assert page.catalog_id == pipeline_catalog_id()
    [smooth] = page.components
    assert page.total == 1
    # Enough to choose the step by; its settings are named and not described.
    assert smooth.model_dump(mode="json") == {
        "id": "prepare.smooth",
        "kind": "transform",
        "group": "prepare",
        "label": "Smooth",
        "description": (
            "Average recent values to calm noise, over observations or over time."
        ),
        "learning": "none",
        "input_type": "features",
        "output_type": "features",
        "settings": [
            "apply_to",
            "result",
            "suffix",
            "method",
            "window_size",
            "time_constant",
        ],
    }
    # A source takes nothing in, which is said and not left out.
    [source] = found(kind="source").components
    assert source.model_dump(mode="json")["input_type"] is None


def test_search_counts_a_rare_word_for_more_than_a_common_one():
    # Most components score features; few are fast.
    page = found("fast features", limit=100)
    assert page.total > 40
    assert "fast" in page.components[0].description.lower()
    # One spelling for both, and an ending does not hide a word.
    assert ids(found("normalise")) == ids(found("normalize"))
    assert ids(found("forecasters"))[0] in ids(found("forecast"))


def test_search_without_words_lists_what_the_filters_leave():
    catalog = pipeline_catalog().components
    everything = found(limit=100)
    assert everything.total == len(catalog)
    assert ids(everything) == [component.id for component in catalog]
    # Words that say nothing about a purpose are no query.
    assert found("what is the", limit=100).total == len(catalog)
    assert ids(found(group="policy")) == [
        "policy.martingale",
        "policy.quantile",
        "policy.exceedance",
    ]
    online = found("scaling", learning="online", limit=100)
    assert online.total and all(item.learning == "online" for item in online.components)
    assert found("scaling", kind="detector", group="normalize").components == []
    # The page is as long as asked for; the total says what there is.
    short = found(kind="detector", limit=3)
    assert len(short.components) == 3 < short.total
    assert found("zzzz").model_dump()["components"] == []


def test_search_bounds_its_query():
    for broken in ({"query": "x" * 201}, {"limit": 0}, {"limit": 101}, {"kind": "x"}):
        with pytest.raises(ValidationError):
            ComponentSearchQuery.model_validate(broken)


def edited(edits, definition=None, layout=None):
    return edit_design(
        DesignEditRequest.model_validate(
            {
                "edits": edits,
                **({} if definition is None else {"definition": definition}),
                **({} if layout is None else {"layout": layout}),
            }
        )
    )


def step(result, identifier):
    return next(node for node in result.definition.nodes if node.id == identifier)


def links(result):
    return sorted((edge.source, edge.target) for edge in result.definition.edges)


FROM_NOTHING = [
    {"op": "add_input", "id": "current", "unit": "A"},
    {"op": "add_step", "component": "source.aligned", "id": "input"},
    {
        "op": "add_step",
        "component": "detector:aberrant_online_isolation_forest",
        "id": "detector",
        "after": "input",
    },
    {"op": "add_step", "component": "calibrate.fixed_split", "after": "detector"},
    {
        "op": "add_step",
        "component": "policy.quantile",
        "id": "policy",
        "after": "calibrate_fixed_split_1",
    },
    {"op": "add_step", "component": "output.evidence", "after": "policy"},
]


def test_edits_build_a_design_that_runs_from_nothing():
    result = edited(FROM_NOTHING)
    assert result.report.valid and result.report.issues == []
    assert result.report.fingerprint
    assert result.added == [
        "input",
        "detector",
        "calibrate_fixed_split_1",
        "policy",
        "output_evidence_1",
    ]
    slot = result.definition.input_slots[0]
    assert (slot.id, slot.label, slot.unit) == ("current", "current", "A")
    assert links(result) == [
        ("calibrate_fixed_split_1", "policy"),
        ("detector", "calibrate_fixed_split_1"),
        ("input", "detector"),
        ("policy", "output_evidence_1"),
    ]
    # The design comes back with the defaults of every setting.
    assert step(result, "policy").params == {
        "mode": "calibrated_quantile",
        "quantile": 1.0,
    }
    # Each step stands a column right of the one it follows, in one row.
    places = [result.layout.nodes[identifier] for identifier in result.added]
    assert [place.x for place in places] == [index * COLUMN for index in range(5)]
    assert {place.y for place in places} == {0}
    # The definition stands once in the answer, not again in its report.
    assert result.report.definition is None and result.report.definition_omitted
    assert result.report.features["detector"][0].name == "current"


def test_a_step_goes_on_a_connection_and_gets_room_there():
    design = edited(FROM_NOTHING)
    result = edited(
        [
            {
                "op": "add_step",
                "component": "prepare.smooth",
                "after": "input",
                "before": "detector",
                "params": {"window_size": 12},
            }
        ],
        design.definition.model_dump(mode="json"),
        design.layout.model_dump(mode="json"),
    )
    assert result.report.valid
    assert result.added == ["prepare_smooth_1"]
    assert ("input", "prepare_smooth_1") in links(result)
    assert ("prepare_smooth_1", "detector") in links(result)
    assert ("input", "detector") not in links(result)
    smooth = step(result, "prepare_smooth_1")
    assert smooth.params == {"method": "exponential", "window_size": 12}
    # A column opens where the detector stood; it and all after it move right.
    assert result.layout.nodes["prepare_smooth_1"].x == COLUMN
    assert result.layout.nodes["detector"].x == 2 * COLUMN
    assert result.layout.nodes["output_evidence_1"].x == 5 * COLUMN
    # Nothing of the design that was sent has changed.
    assert design.layout.nodes["detector"].x == COLUMN


def drawn(spacing=COLUMN):
    """The adaptive template with its cards in one row, a spacing apart."""
    definition = template()
    layout = {
        "nodes": {
            node.id: {"x": index * spacing, "y": 96}
            for index, node in enumerate(definition.nodes)
        }
    }
    return definition.model_dump(mode="json"), layout


def test_a_step_between_distant_cards_stands_in_the_middle():
    definition, layout = drawn(3 * COLUMN)
    layout["nodes"]["detector"]["y"] = 160
    result = edited(
        [
            {
                "op": "add_step",
                "component": "prepare.despike",
                "after": "input",
                "before": "detector",
            }
        ],
        definition,
        layout,
    )
    place = result.layout.nodes["prepare_despike_1"]
    assert (place.x, place.y) == (432, 128)
    assert result.layout.nodes["detector"].x == 3 * COLUMN


def test_a_second_step_of_a_kind_is_numbered_and_stands_clear():
    result = edited(
        [
            {"op": "add_step", "component": "prepare.smooth", "after": "input"},
            {"op": "add_step", "component": "prepare.smooth", "after": "input"},
            {"op": "add_step", "component": "prepare.smooth", "label": "Slow"},
            {"op": "add_step", "component": "prepare.despike", "before": "detector"},
        ],
        *drawn(),
    )
    first, second, third = (step(result, f"prepare_smooth_{n}") for n in (1, 2, 3))
    assert (first.label, second.label, third.label) == (None, "Smooth 2", "Slow")
    places = result.layout.nodes
    # Without a neighbour a step goes right of the rightmost card.
    assert places["prepare_smooth_3"].x == max(place.x for place in places.values())
    # One neighbour with one connection on that side: the step goes into it,
    # so the chain stays whole instead of ending in a dead end.
    assert {
        ("input", "prepare_smooth_2"),
        ("prepare_smooth_2", "prepare_smooth_1"),
        ("prepare_smooth_1", "prepare_despike_1"),
        ("prepare_despike_1", "detector"),
    } <= set(links(result))
    assert ("input", "detector") not in links(result)
    assert places["prepare_smooth_2"].x < places["prepare_smooth_1"].x
    assert places["prepare_despike_1"].x < places["detector"].x
    # Only the step with no neighbour ends nowhere.
    assert not result.report.valid
    assert {
        issue.node_id for issue in result.report.issues if issue.code == "disconnected"
    } == {"prepare_smooth_3"}


def test_one_neighbour_with_several_connections_starts_a_branch():
    definition, layout = drawn()
    result = edited(
        [
            {
                "op": "add_step",
                "component": "prepare.smooth",
                "id": "a",
                "after": "input",
            },
            {"op": "connect", "source": "input", "target": "detector"},
        ],
        definition,
        layout,
    )
    assert ("input", "a") in links(result)
    result = edited(
        [
            {
                "op": "add_step",
                "component": "prepare.despike",
                "id": "b",
                "after": "input",
            }
        ],
        result.definition.model_dump(mode="json"),
        result.layout.model_dump(mode="json"),
    )
    assert ("input", "b") in links(result)
    assert not any(edge.source == "b" for edge in result.definition.edges)
    # A step that does not hand its features on is only connected on its side.
    result = edited(
        [
            {
                "op": "add_step",
                "component": "detector:aberrant_online_isolation_forest",
                "id": "second",
                "after": "input",
            }
        ],
        *drawn(),
    )
    assert ("input", "second") in links(result)
    assert ("input", "detector") in links(result)


def chain():
    """Input, Smooth, Despike and the rest of the adaptive template."""
    design = edited(
        [
            {
                "op": "add_step",
                "component": "prepare.smooth",
                "id": "smooth",
                "after": "input",
                "before": "detector",
            },
            {
                "op": "add_step",
                "component": "prepare.despike",
                "id": "despike",
                "after": "smooth",
                "before": "detector",
            },
        ],
        *drawn(),
    )
    assert design.report.valid
    return (
        design.definition.model_dump(mode="json"),
        design.layout.model_dump(mode="json"),
    )


def test_removing_a_step_hands_its_input_on():
    definition, layout = chain()
    result = edited([{"op": "remove_step", "id": "smooth"}], definition, layout)
    assert result.report.valid
    assert ("input", "despike") in links(result)
    assert "smooth" not in result.layout.nodes
    assert all(node.id != "smooth" for node in result.definition.nodes)
    # Or leaves the gap open, for the caller to close another way.
    open_ended = edited(
        [{"op": "remove_step", "id": "smooth", "reconnect": False}], definition, layout
    )
    assert ("input", "despike") not in links(open_ended)
    assert not open_ended.report.valid
    # A detector takes features and gives scores, so nothing is handed on.
    scores = edited([{"op": "remove_step", "id": "detector"}], definition, layout)
    assert all(edge.source != "despike" for edge in scores.definition.edges)


def test_settings_change_one_at_a_time():
    definition, layout = chain()
    result = edited(
        [
            {
                "op": "set_params",
                "id": "smooth",
                "params": {"window_size": 30, "method": "mean"},
            },
            {"op": "set_params", "id": "smooth", "unset": ["method"]},
            {"op": "set_settings", "training_window_size": 500},
            {"op": "set_label", "id": "smooth", "label": "  Calm it down "},
        ],
        definition,
        layout,
    )
    smooth = step(result, "smooth")
    assert smooth.params == {"method": "exponential", "window_size": 30}
    assert smooth.label == "Calm it down"
    settings = result.definition.settings
    assert (settings.training_window_size, settings.seed) == (500, 42)
    assert (
        settings.calibration_window_size == template().settings.calibration_window_size
    )
    # A title is not part of what runs.
    titled, untitled = (
        edited(
            [{"op": "set_label", "id": "smooth", "label": label}], definition, layout
        )
        for label in ("Calm it down", None)
    )
    assert step(untitled, "smooth").label is None
    assert titled.report.fingerprint == untitled.report.fingerprint
    # A value the step does not take is an issue of the design, at that step.
    wrong = edited(
        [{"op": "set_params", "id": "smooth", "params": {"window_size": 0}}],
        definition,
        layout,
    )
    [issue] = wrong.report.issues
    assert (issue.code, issue.node_id, issue.parameter_path) == (
        "parameters",
        "smooth",
        ["window_size"],
    )


def test_replacing_a_step_keeps_its_place_and_connections():
    definition, layout = chain()
    layout["switched_off"] = {
        "smooth": {"component": "prepare.change", "params": {}},
        "despike": {"component": "prepare.change", "params": {}},
    }
    result = edited(
        [{"op": "replace_step", "id": "smooth", "component": "prepare.change"}],
        definition,
        layout,
    )
    change = step(result, "smooth")
    assert (change.kind, change.component) == ("transform", "prepare.change")
    assert "window_size" not in change.params
    assert links(result) == links(edited([{"op": "set_settings"}], definition, layout))
    assert (
        result.layout.nodes["smooth"]
        == PipelineLayout.model_validate(layout).nodes["smooth"]
    )
    # What a step was before it was switched off goes with the step it was.
    assert set(result.layout.switched_off) == {"despike"}
    removed = edited([{"op": "remove_step", "id": "despike"}], definition, layout)
    assert set(removed.layout.switched_off) == {"smooth"}
    with pytest.raises(EditError, match="switched off"):
        edited([{"op": "set_params", "id": "smooth", "params": {}}], definition, layout)


def test_connections_are_made_and_taken_away():
    definition, layout = chain()
    result = edited(
        [
            {"op": "disconnect", "source": "smooth", "target": "despike"},
            {
                "op": "add_step",
                "component": "features.merge",
                "id": "both",
                "before": "detector",
            },
            {"op": "connect", "source": "smooth", "target": "both"},
            {"op": "connect", "source": "input", "target": "despike"},
            {"op": "connect", "source": "despike", "target": "both"},
        ],
        definition,
        layout,
    )
    # Both branches carry the same feature, which a merge does not take; the
    # connections themselves are in order.
    assert [issue.code for issue in result.report.issues] == ["feature_schema"]
    # A merge takes each connection as its last.
    merged = sorted(
        (edge.order, edge.source)
        for edge in result.definition.edges
        if edge.target == "both"
    )
    assert merged == [(0, "smooth"), (1, "despike")]
    # A single input takes a new connection in place of the one it had.
    replaced = edited(
        [{"op": "connect", "source": "input", "target": "detector"}], definition, layout
    )
    assert [e.source for e in replaced.definition.edges if e.target == "detector"] == [
        "input"
    ]
    # A loop is an issue of the design, as it is in the editor.
    loop = edited(
        [{"op": "connect", "source": "despike", "target": "smooth"}], definition, layout
    )
    assert "cycle" in {issue.code for issue in loop.report.issues}


def test_notes_stand_above_the_step_they_are_about():
    definition, layout = chain()
    long = "The current is noisy at this sampling rate. " * 6
    result = edited(
        [
            {
                "op": "add_note",
                "text": "  Smoothed over a minute.  ",
                "beside": "smooth",
            },
            {"op": "add_note", "text": long, "beside": "smooth"},
            {"op": "add_note", "text": "About the whole design."},
        ],
        definition,
        layout,
    )
    assert result.added == ["note_1", "note_2", "note_3"]
    first, second, third = result.layout.notes
    card = result.layout.nodes["smooth"]
    assert first.text == "Smoothed over a minute."
    # One line and a grid line of air: the note ends just above its card.
    assert (first.x, first.y) == (card.x, card.y - 64)
    # A longer note is taller, and a second note stands above the first.
    assert second.x == card.x and second.y < first.y - 200
    # A note about no step stands above the first card.
    start = result.layout.nodes["input"]
    assert (third.x, third.y) == (start.x, start.y - 64)
    # Notes are part of the drawing; the design runs as it did.
    assert (
        result.report.fingerprint
        == edited([{"op": "set_settings"}], definition, layout).report.fingerprint
    )
    fewer = edited(
        [{"op": "remove_note", "id": "note_2"}, {"op": "add_note", "text": "Again."}],
        result.definition.model_dump(mode="json"),
        result.layout.model_dump(mode="json"),
    )
    assert [note.id for note in fewer.layout.notes] == ["note_1", "note_3", "note_4"]
    assert fewer.added == ["note_4"]


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        (
            [{"op": "set_params", "id": "gone"}],
            r"Edit 1 \(set_params\): The design has no step 'gone'",
        ),
        (
            [
                {"op": "set_label", "id": "smooth", "label": "x"},
                {"op": "add_step", "component": "prepare.nothing"},
            ],
            r"Edit 2 \(add_step\): The catalog has no component 'prepare.nothing'",
        ),
        (
            [{"op": "add_step", "component": "prepare.smooth", "id": "smooth"}],
            "already has a step 'smooth'",
        ),
        (
            [{"op": "add_step", "component": "prepare.smooth", "after": "gone"}],
            "no step 'gone'",
        ),
        (
            [
                {
                    "op": "add_step",
                    "component": "prepare.smooth",
                    "after": "smooth",
                    "before": "smooth",
                }
            ],
            "two different steps",
        ),
        (
            [{"op": "replace_step", "id": "smooth", "component": "x"}],
            "no component 'x'",
        ),
        ([{"op": "remove_step", "id": "gone"}], "no step 'gone'"),
        (
            [{"op": "connect", "source": "smooth", "target": "smooth"}],
            "cannot connect to itself",
        ),
        (
            [{"op": "connect", "source": "smooth", "target": "despike"}],
            "connected already",
        ),
        (
            [{"op": "disconnect", "source": "input", "target": "despike"}],
            "no connection from 'input' to 'despike'",
        ),
        ([{"op": "add_input", "id": "value"}], "already has an input 'value'"),
        ([{"op": "remove_input", "id": "gone"}], "no input 'gone'"),
        ([{"op": "add_note", "text": "   "}], "A note says something"),
        ([{"op": "add_note", "text": "x", "beside": "gone"}], "no step 'gone'"),
        ([{"op": "remove_note", "id": "note_9"}], "no note 'note_9'"),
    ],
)
def test_an_edit_that_cannot_be_made_stops_the_request_and_names_itself(edits, message):
    definition, layout = chain()
    with pytest.raises(EditError, match=message):
        edited(edits, definition, layout)


def test_a_design_holds_no_more_than_its_limits():
    steps = [{"op": "add_step", "component": "prepare.smooth"}] * 60
    full = edited(steps, template().model_dump(mode="json"))
    assert len(full.definition.nodes) == 65
    with pytest.raises(
        EditError, match=r"Edit 61 \(add_step\): A design holds up to 65 steps"
    ):
        edited(
            [*steps, {"op": "add_step", "component": "prepare.smooth"}],
            template().model_dump(mode="json"),
        )
    notes = [{"op": "add_note", "text": "x"}] * 50
    assert len(edited(notes).layout.notes) == 50
    with pytest.raises(EditError, match="up to 50 notes"):
        edited([*notes, {"op": "add_note", "text": "x"}])
    crowded = {"input_slots": [{"id": f"r{n}", "label": "R"} for n in range(100)]}
    with pytest.raises(EditError, match="up to 100 readings"):
        edited([{"op": "add_input", "id": "one_more"}], crowded)


def test_a_request_names_its_edits_and_bounds_them():
    for broken in (
        {"edits": []},
        {"edits": [{"op": "set_settings"}] * 101},
        {"edits": [{"op": "rename_step", "id": "a"}]},
        {"edits": [{"op": "add_step"}]},
        {"edits": [{"op": "add_step", "component": "prepare.smooth", "id": "9 lives"}]},
        {
            "edits": [
                {"op": "add_step", "component": "prepare.smooth", "position": {"x": 0}}
            ]
        },
        {"edits": [{"op": "add_note", "text": "x" * 2001}]},
        {"edits": [{"op": "set_settings", "training_window_size": 1}]},
    ):
        with pytest.raises(ValidationError):
            DesignEditRequest.model_validate(broken)


def test_a_new_calibration_step_brings_the_policy_that_fits_it():
    result = edited(
        [{"op": "replace_step", "id": "calibrate", "component": "calibrate.split"}],
        *drawn(),
    )
    policy = step(result, "policy")
    assert policy.component == "policy.exceedance"
    assert result.report.valid
    assert result.also and "policy" in result.also[0]
    # And back: the fixed split freezes a threshold again.
    back = edited(
        [
            {
                "op": "replace_step",
                "id": "calibrate",
                "component": "calibrate.fixed_split",
            }
        ],
        result.definition.model_dump(mode="json"),
        result.layout.model_dump(mode="json"),
    )
    assert step(back, "policy").component == "policy.quantile"
    assert back.report.valid
    # A step that is not the calibration leaves the policy alone.
    plain = edited(
        [
            {
                "op": "replace_step",
                "id": "detector",
                "component": "detector:aberrant_half_space_trees",
            }
        ],
        *drawn(),
    )
    assert plain.also == []
    assert step(plain, "policy").component == "policy.quantile"


def test_a_detector_that_keeps_a_sample_needs_a_training_window_as_long():
    result = edited(
        [
            {
                "op": "add_step",
                "component": "adaptive.min_max_scaler",
                "after": "input",
                "params": {"clip": True},
            },
            {
                "op": "replace_step",
                "id": "detector",
                "component": "detector:aberrant_half_space_trees",
            },
            {"op": "set_settings", "training_window_size": 120},
        ],
        *drawn(),
    )
    issues = [i for i in result.report.issues if i.code == "training_window"]
    assert len(issues) == 1 and issues[0].node_id == "detector"
    assert "250" in issues[0].message and "120" in issues[0].message
    smaller = edited(
        [{"op": "set_params", "id": "detector", "params": {"window_size": 100}}],
        result.definition.model_dump(mode="json"),
        result.layout.model_dump(mode="json"),
    )
    assert "training_window" not in {i.code for i in smaller.report.issues}


def test_a_design_of_rules_is_told_its_calibration_window_is_what_it_waits_for():
    rule = [
        {"op": "replace_step", "id": "detector", "component": "rule.score"},
    ]
    long = edited(rule, *drawn())
    codes = {i.code: i.severity for i in long.report.issues}
    assert codes.get("rule_calibration") == "warning"
    short = edited(
        [*rule, {"op": "set_settings", "calibration_window_size": 30}], *drawn()
    )
    assert "rule_calibration" not in {i.code for i in short.report.issues}
