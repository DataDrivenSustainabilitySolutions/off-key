"""Find components by what they are for, in a form short enough to read whole.

The catalog says everything about every component, which is more than a reader
can take in to choose one. A search answers with a few lines per component:
what it is called, where it belongs and the sentence that says what it does.
"""

import math
import re
from collections.abc import Iterable

from ..schemas.pipeline_tools import (
    ComponentSearchPage,
    ComponentSearchQuery,
    ComponentSummary,
)
from ..schemas.pipelines import ComponentField, PipelineComponent
from .pipeline_catalog import pipeline_catalog_id, pipeline_components

_WORD = re.compile(r"[a-z0-9]+")
# Words that say nothing about what a step is for.
_FILLER = frozenset(
    _WORD.findall(
        "a an and are as at be by can do does for from how i in is it my need of "
        "on or that the to want what when which with"
    )
)
_ENDINGS = ("ies", "ing", "ed", "es", "er", "s", "e", "y")
# How much a word counts by where it is found: a name before a description
# before the small print of a setting.
_NAME, _ID, _PLACE, _DESCRIPTION, _DETAILS, _SETTING, _SETTING_HELP = (
    6.0,
    5.0,
    4.0,
    3.0,
    1.5,
    1.5,
    0.5,
)


# Normalise is normalize: one spelling for both, in the query and in the catalog.
_BRITISH = re.compile(r"is(e|ed|es|ing|er|ation)$")


def _stem(word: str) -> str:
    """A word without its ending, so smoothing finds Smooth and spikes Despike."""
    word = _BRITISH.sub(r"iz\1", word)
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(text.lower())}


def _wanted(query: str) -> list[str]:
    """The stems a query asks for, each once, in the order they were written."""
    words = [word for word in _WORD.findall(query.lower()) if word not in _FILLER]
    return list(dict.fromkeys(_stem(word) for word in words))


def _settings(fields: Iterable[ComponentField]) -> tuple[set[str], set[str]]:
    """The stems of what settings are called and of what is said about them."""
    names: set[str] = set()
    explained: set[str] = set()
    for field in fields:
        names |= _stems(f"{field.name} {field.label}")
        explained |= _stems(" ".join([field.description, *(field.options or [])]))
        nested = [
            *field.fields,
            *(v for vs in (field.variants or {}).values() for v in vs),
        ]
        inner_names, inner_explained = _settings(nested)
        names |= inner_names
        explained |= inner_explained
    return names, explained


def _places(component: PipelineComponent) -> list[tuple[float, set[str]]]:
    names, explained = _settings(component.fields)
    return [
        (_NAME, _stems(component.label)),
        (_ID, _stems(component.id)),
        (
            _PLACE,
            _stems(
                f"{component.group} {component.kind} {component.library or ''} "
                f"{component.learning if component.learning != 'none' else ''}"
            ),
        ),
        (_DESCRIPTION, _stems(component.description)),
        (_DETAILS, _stems(component.details)),
        (_SETTING, names),
        (_SETTING_HELP, explained),
    ]


def _found(wanted: str, stems: set[str]) -> float:
    """1 where the word is there, a half where only part of one is, else 0."""
    if wanted in stems:
        return 1.0
    if len(wanted) >= 4 and any(
        wanted in stem or (len(stem) >= 4 and wanted.startswith(stem)) for stem in stems
    ):
        return 0.5
    return 0.0


def _fit(places: list[tuple[float, set[str]]], wanted: list[str]) -> list[float]:
    """For each word, how prominently a component answers it; 0 where not at all."""
    return [
        max(weight * _found(word, stems) for weight, stems in places) for word in wanted
    ]


def _ranked(
    components: list[PipelineComponent], wanted: list[str]
) -> list[PipelineComponent]:
    """The components that answer a word, the best answer first.

    A word few components answer tells more than one most of them answer, so
    it counts for more: fast says more about a detector than detector does.
    """
    fits = [_fit(_places(component), wanted) for component in components]
    answered = [sum(fit[index] > 0 for fit in fits) for index in range(len(wanted))]
    rarity = [
        math.log(1 + len(components) / count) if count else 0 for count in answered
    ]
    scored = [
        (
            sum(weight * rare for weight, rare in zip(fit, rarity, strict=True)),
            component,
        )
        for fit, component in zip(fits, components, strict=True)
    ]
    # A stable sort keeps the order of the catalog among equal fits.
    return [
        component
        for score, component in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ]


def component_summary(component: PipelineComponent) -> ComponentSummary:
    return ComponentSummary(
        id=component.id,
        kind=component.kind,
        group=component.group,
        label=component.label,
        description=component.description,
        library=component.library,
        learning=component.learning,
        input_type=component.input_type,
        output_type=component.output_type,
        settings=[field.name for field in component.fields],
    )


def search_components(query: ComponentSearchQuery) -> ComponentSearchPage:
    """The components that fit a query, the best fit first.

    A component fits when it answers at least one word of the query: in its
    name, its place in the catalog, its description or its settings. Words in
    a name count for more than words in the small print, and rare words for
    more than common ones. Without words to look for, every component the
    filters leave is listed in the order of the catalog.
    """
    kept = [
        component
        for component in pipeline_components()
        if (query.kind is None or component.kind == query.kind)
        and (query.group is None or component.group == query.group)
        and (query.learning is None or component.learning == query.learning)
    ]
    wanted = _wanted(query.query)
    if wanted:
        kept = _ranked(kept, wanted)
    return ComponentSearchPage(
        catalog_id=pipeline_catalog_id(),
        total=len(kept),
        components=[component_summary(item) for item in kept[: query.limit]],
    )
