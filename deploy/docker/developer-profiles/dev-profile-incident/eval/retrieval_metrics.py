# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline retrieval metrics for the MVP2 retrieval benchmark (Track R).

Implements ``.docs/mvp2/eval.md`` §3.4 (retrieval and filtering semantics) and §3.5
(metrics, aggregation and uncertainty) as pure functions over already-collected search
results. Nothing here calls the search route, a database or a model: the harness
(work-order step 3) turns each ``POST /api/v1/incidents/search`` response into a
:class:`QueryInstance` and passes the instances in.

**Lists (§3.4).** Every list is cut from one candidate pool ``C`` (the hits of one call
with ``top_k = 20``, ``hide_rejected = false``, in returned order, never re-sorted), so
every comparison is paired on identical candidates. For a budget ``K``:

- ``B`` baseline: ``C[:K]``.
- ``S`` post-filter: ``C[:K]`` without ``rejected`` items, order kept (can be shorter than K).
- ``F`` fill-to-K: the first K non-``rejected`` items of ``C`` (short when the pool runs out).

``unverified`` counts as kept; ``drop_unverified=True`` gives the sensitivity variant of
``S`` and ``F`` with ``unverified`` dropped too (``B`` never changes).

**Per-instance metrics (§3.5).** A query instance is one variant (the seed text or one
paraphrase) in one repeat. With ``hits = |L ∩ Rel(q)|``:

- ``standard_precision``: ``hits / K``; empty slots count as misses.
- ``returned_precision``: ``hits / |L|``; undefined when ``|L| = 0``.
- ``recall``: ``hits / |Rel|``.
- ``f1``: harmonic mean of standard precision and recall; 0 when both are 0.
- ``mrr``: 1 / position of the first relevant item in ``L``; 0 when there is none.
- ``false_positives``: ``|L| − hits``.
- ``coverage``: ``|L| / K``, and ``empty``: 1 when ``|L| = 0``, else 0 (every instance).
- ``zero_relevant_length``: ``|L|``, and ``zero_relevant_nonempty``: 1 when ``|L| > 0``, else 0
  (zero-relevant queries only).

A positive query has at least one relevant item. Zero-relevant queries are excluded from
precision, recall, F1, MRR and positive-query false positives, and contribute only to the
``zero_relevant_*`` metrics (and to coverage and the empty share, which use every instance).

**Duplicates.** The route returns each item key once, so a duplicate key in a pool is a
harness or route defect. It is not hidden: a repeated key occupies its slot (it counts in
``|L|``, coverage and MRR positions) but is never a second hit, so it shows up as a false
positive and in :attr:`ListMetrics.duplicates`.

**Aggregation (§3.5).** Each variant's value is the mean over its repeats; each seed's value
is the mean over its eligible variants (equal weight per variant); reported means are
macro-averages over seeds, overall and per class.

**Uncertainty (§3.5).** 95% percentile intervals from a cluster bootstrap over seeds: a
resampled seed brings all its variants and repeats. Differences between lists (``S − B``,
``F − B``) are computed per seed and then bootstrapped, so every difference is paired.
Returned precision in a comparison uses only the instances where *both* lists are non-empty
(the same instances on both sides), and the drops are counted. Resampling draws indices
from ``random.Random(seed).random()``, whose sequence Python guarantees for a given seed,
so a result is reproducible from its seed; the draws for one ``(seeds, resamples, seed)``
shape are made once and reused, and numpy only averages them.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from statistics import fmean
from typing import Literal

import numpy as np

Verdict = Literal["confirmed", "rejected", "unverified"]
ListName = Literal["B", "S", "F"]

VERDICTS: frozenset[str] = frozenset({"confirmed", "rejected", "unverified"})
LIST_NAMES: tuple[ListName, ...] = ("B", "S", "F")
# The budgets of §3.4.
DEFAULT_BUDGETS: tuple[int, ...] = (1, 3, 5, 10)
# The paired differences of §3.5 and §3.6, written system minus baseline.
DEFAULT_COMPARISONS: tuple[tuple[ListName, ListName], ...] = (("S", "B"), ("F", "B"))
DEFAULT_CONFIDENCE = 0.95
DEFAULT_RESAMPLES = 10_000

POSITIVE_METRICS: tuple[str, ...] = (
    "standard_precision",
    "returned_precision",
    "recall",
    "f1",
    "mrr",
    "false_positives",
)
ALL_INSTANCE_METRICS: tuple[str, ...] = ("coverage", "empty")
ZERO_RELEVANT_METRICS: tuple[str, ...] = ("zero_relevant_length", "zero_relevant_nonempty")
METRICS: tuple[str, ...] = POSITIVE_METRICS + ALL_INSTANCE_METRICS + ZERO_RELEVANT_METRICS


@dataclass(frozen=True)
class Candidate:
    """One hit of the candidate pool: its item key, similarity score and critic verdict."""

    key: Hashable
    similarity: float
    verdict: Verdict

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VERDICTS)}, got {self.verdict!r}")
        if not isinstance(self.similarity, int | float) or not math.isfinite(self.similarity):
            raise ValueError(f"similarity must be a finite number, got {self.similarity!r}")


@dataclass(frozen=True)
class QueryInstance:
    """One variant of one seed query in one repeat, with its candidate pool and relevant item keys.

    ``pool`` is in the order the search route returned it (rank order), at most ``top_k`` long.
    ``relevant`` is the variant's exhaustive label set over the pinned corpus; an empty set
    makes the variant a zero-relevant query.
    """

    seed_id: str
    variant_id: str
    repeat: int
    query_class: str
    pool: tuple[Candidate, ...]
    relevant: frozenset[Hashable]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool", tuple(self.pool))
        object.__setattr__(self, "relevant", frozenset(self.relevant))
        if not all(isinstance(candidate, Candidate) for candidate in self.pool):
            raise TypeError("pool must hold Candidate objects")

    @property
    def positive(self) -> bool:
        return bool(self.relevant)


@dataclass(frozen=True)
class ListMetrics:
    """The §3.5 metrics of one list for one query instance; ``None`` where a metric is undefined."""

    k: int
    length: int
    hits: int
    duplicates: int
    relevant_count: int
    standard_precision: float | None
    returned_precision: float | None
    recall: float | None
    f1: float | None
    mrr: float | None
    false_positives: float | None
    coverage: float
    empty: float
    zero_relevant_length: float | None
    zero_relevant_nonempty: float | None

    def value(self, metric: str) -> float | None:
        if metric not in METRICS:
            raise ValueError(f"unknown metric {metric!r}; expected one of {METRICS}")
        return getattr(self, metric)


@dataclass(frozen=True)
class Estimate:
    """A macro-average over seeds with its bootstrap interval (``None`` with no seed)."""

    mean: float | None
    interval: tuple[float, float] | None
    seeds: int

    def as_dict(self) -> dict[str, object]:
        return {"mean": self.mean, "ci": list(self.interval) if self.interval else None, "seeds": self.seeds}


@dataclass(frozen=True)
class PairedDifference:
    """``first − second`` averaged over the seeds both lists have a value for, with a paired interval.

    ``dropped`` is set for returned precision only: the positive query instances left out because
    the first list, the second list or both were empty.
    """

    first: ListName
    second: ListName
    metric: str
    estimate: Estimate
    dropped: dict[str, int] | None = None

    def as_dict(self) -> dict[str, object]:
        result = self.estimate.as_dict()
        if self.dropped is not None:
            result["dropped"] = dict(self.dropped)
        return result


def _check_budget(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError(f"the budget K must be a positive integer, got {k!r}")


def _kept(candidate: Candidate, drop_unverified: bool) -> bool:
    if candidate.verdict == "rejected":
        return False
    return not (drop_unverified and candidate.verdict == "unverified")


def cut_list(
    pool: Sequence[Candidate], list_name: ListName, k: int, *, drop_unverified: bool = False
) -> tuple[Candidate, ...]:
    """The ``B``, ``S`` or ``F`` list of budget ``k`` from one candidate pool (§3.4)."""
    _check_budget(k)
    if list_name == "B":
        return tuple(pool[:k])
    if list_name == "S":
        return tuple(candidate for candidate in pool[:k] if _kept(candidate, drop_unverified))
    if list_name == "F":
        return tuple(candidate for candidate in pool if _kept(candidate, drop_unverified))[:k]
    raise ValueError(f"list_name must be one of {LIST_NAMES}, got {list_name!r}")


def list_metrics(items: Sequence[Candidate], relevant: Iterable[Hashable], k: int) -> ListMetrics:
    """The §3.5 metrics of one list ``items`` cut at budget ``k`` against the relevant keys."""
    _check_budget(k)
    relevant = frozenset(relevant)
    seen: set[Hashable] = set()
    hits = duplicates = 0
    first_relevant: int | None = None
    for position, candidate in enumerate(items, start=1):
        if candidate.key in seen:
            duplicates += 1
            continue
        seen.add(candidate.key)
        if candidate.key in relevant:
            hits += 1
            if first_relevant is None:
                first_relevant = position
    length = len(items)
    positive = bool(relevant)
    standard_precision = hits / k if positive else None
    recall = hits / len(relevant) if positive else None
    f1: float | None = None
    if standard_precision is not None and recall is not None:
        total = standard_precision + recall
        f1 = 0.0 if total == 0 else 2 * standard_precision * recall / total
    return ListMetrics(
        k=k,
        length=length,
        hits=hits,
        duplicates=duplicates,
        relevant_count=len(relevant),
        standard_precision=standard_precision,
        returned_precision=hits / length if positive and length else None,
        recall=recall,
        f1=f1,
        mrr=(1 / first_relevant if first_relevant else 0.0) if positive else None,
        false_positives=float(length - hits) if positive else None,
        coverage=length / k,
        empty=1.0 if length == 0 else 0.0,
        zero_relevant_length=None if positive else float(length),
        zero_relevant_nonempty=None if positive else (1.0 if length else 0.0),
    )


def instance_metrics(
    instance: QueryInstance, list_name: ListName, k: int, *, drop_unverified: bool = False
) -> ListMetrics:
    """The metrics of one list of one query instance."""
    return list_metrics(cut_list(instance.pool, list_name, k, drop_unverified=drop_unverified), instance.relevant, k)


def boundary_tie(pool: Sequence[Candidate], k: int) -> bool:
    """Whether positions K and K+1 of the pool have exactly equal similarity (§3.4).

    The RPC orders by cosine distance with no tie-breaker, so for such a pool ``C[:K]`` may not
    match a separate ``top_k = K`` call.
    """
    _check_budget(k)
    return len(pool) > k and pool[k - 1].similarity == pool[k].similarity


def validate_instances(instances: Sequence[QueryInstance]) -> None:
    """Raise ``ValueError`` on input the aggregation would silently misread.

    Each ``(seed_id, variant_id, repeat)`` appears once; a seed has one class; a variant has the
    same relevant set in every repeat (labels are per query, not per call).
    """
    seen: set[tuple[str, str, int]] = set()
    seed_class: dict[str, str] = {}
    variant_relevant: dict[tuple[str, str], frozenset[Hashable]] = {}
    for instance in instances:
        identity = (instance.seed_id, instance.variant_id, instance.repeat)
        if identity in seen:
            raise ValueError(f"query instance {identity} appears more than once")
        seen.add(identity)
        if seed_class.setdefault(instance.seed_id, instance.query_class) != instance.query_class:
            raise ValueError(f"seed {instance.seed_id!r} has more than one class")
        variant = (instance.seed_id, instance.variant_id)
        if variant_relevant.setdefault(variant, instance.relevant) != instance.relevant:
            raise ValueError(f"variant {variant} has different relevant sets across repeats")


def _ordered(instances: Iterable[QueryInstance], query_class: str | None) -> list[QueryInstance]:
    """The instances of one class (or all), in a fixed order so results never depend on input order."""
    selected = [i for i in instances if query_class is None or i.query_class == query_class]
    return sorted(selected, key=lambda i: (i.seed_id, i.variant_id, i.repeat))


def _seed_means(values: Iterable[tuple[QueryInstance, float]]) -> dict[str, float]:
    """Repeat mean per variant, then the mean over each seed's variants that have a value."""
    by_variant: dict[tuple[str, str], list[float]] = defaultdict(list)
    for instance, value in values:
        by_variant[(instance.seed_id, instance.variant_id)].append(value)
    by_seed: dict[str, list[float]] = defaultdict(list)
    for (seed_id, _), repeat_values in sorted(by_variant.items()):
        by_seed[seed_id].append(fmean(repeat_values))
    return {seed_id: fmean(variant_values) for seed_id, variant_values in sorted(by_seed.items())}


def seed_values(
    instances: Iterable[QueryInstance],
    metric: str,
    list_name: ListName,
    k: int,
    *,
    drop_unverified: bool = False,
    query_class: str | None = None,
    paired_with: ListName | None = None,
) -> dict[str, float]:
    """Each seed's value of ``metric`` for one list and budget (§3.5 aggregation steps 1 and 2).

    Instances where the metric is undefined are left out, so a seed with no eligible variant
    has no value. With ``paired_with``, returned precision uses only the instances where both
    lists are non-empty.
    """
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {METRICS}")
    values: list[tuple[QueryInstance, float]] = []
    for instance in _ordered(instances, query_class):
        metrics = instance_metrics(instance, list_name, k, drop_unverified=drop_unverified)
        value = metrics.value(metric)
        if value is None:
            continue
        if metric == "returned_precision" and paired_with is not None:
            other = instance_metrics(instance, paired_with, k, drop_unverified=drop_unverified)
            if other.length == 0:
                continue
        values.append((instance, value))
    return _seed_means(values)


@lru_cache(maxsize=64)
def _resample_indices(count: int, resamples: int, seed: int) -> np.ndarray:
    """``resamples`` rows of ``count`` seed indices drawn with replacement, from ``random.Random(seed)``."""
    rng = random.Random(seed)
    draws = [int(rng.random() * count) for _ in range(resamples * count)]
    indices = np.asarray(draws, dtype=np.intp).reshape(resamples, count)
    indices.setflags(write=False)
    return indices


def bootstrap_interval(
    values: Sequence[float],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float, float] | None:
    """Percentile interval of the mean of ``values`` (one value per seed) by resampling seeds.

    Resampling a seed's value is the cluster bootstrap of §3.5: the value already averages all
    the seed's variants and repeats. ``None`` when there is no value. Descriptive only.
    """
    if resamples < 1:
        raise ValueError(f"resamples must be at least 1, got {resamples!r}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence!r}")
    if not values:
        return None
    means = np.asarray(values, dtype=float)[_resample_indices(len(values), resamples, seed)].mean(axis=1)
    tail = (1 - confidence) / 2
    # Linear interpolation between the closest ranks (numpy's default, the common "type 7").
    low, high = np.quantile(means, [tail, 1 - tail])
    return float(low), float(high)


def estimate(
    instances: Iterable[QueryInstance],
    metric: str,
    list_name: ListName,
    k: int,
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    drop_unverified: bool = False,
    query_class: str | None = None,
) -> Estimate:
    """The macro-average over seeds of one metric for one list and budget, with its interval."""
    per_seed = seed_values(instances, metric, list_name, k, drop_unverified=drop_unverified, query_class=query_class)
    values = list(per_seed.values())
    return Estimate(
        mean=fmean(values) if values else None,
        interval=bootstrap_interval(values, resamples=resamples, seed=seed, confidence=confidence),
        seeds=len(values),
    )


def returned_precision_drops(
    instances: Iterable[QueryInstance],
    first: ListName,
    second: ListName,
    k: int,
    *,
    drop_unverified: bool = False,
    query_class: str | None = None,
) -> dict[str, int]:
    """Positive query instances a returned-precision comparison leaves out, by which list was empty."""
    drops = {"first_empty": 0, "second_empty": 0, "both_empty": 0}
    for instance in _ordered(instances, query_class):
        if not instance.positive:
            continue
        first_empty = not cut_list(instance.pool, first, k, drop_unverified=drop_unverified)
        second_empty = not cut_list(instance.pool, second, k, drop_unverified=drop_unverified)
        if first_empty and second_empty:
            drops["both_empty"] += 1
        elif first_empty:
            drops["first_empty"] += 1
        elif second_empty:
            drops["second_empty"] += 1
    return drops


def paired_difference(
    instances: Iterable[QueryInstance],
    metric: str,
    first: ListName,
    second: ListName,
    k: int,
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    drop_unverified: bool = False,
    query_class: str | None = None,
) -> PairedDifference:
    """``first − second`` for one metric and budget, computed per seed and then bootstrapped.

    Both sides are cut from the same pools, and the bootstrap resamples seeds, carrying each
    seed's own difference, so the comparison stays paired. Only seeds with a value on both
    sides count.
    """
    instances = list(instances)
    paired = metric == "returned_precision"
    common = {"drop_unverified": drop_unverified, "query_class": query_class}
    first_values = seed_values(instances, metric, first, k, paired_with=second if paired else None, **common)
    second_values = seed_values(instances, metric, second, k, paired_with=first if paired else None, **common)
    shared = sorted(first_values.keys() & second_values.keys())
    differences = [first_values[seed_id] - second_values[seed_id] for seed_id in shared]
    return PairedDifference(
        first=first,
        second=second,
        metric=metric,
        estimate=Estimate(
            mean=fmean(differences) if differences else None,
            interval=bootstrap_interval(differences, resamples=resamples, seed=seed, confidence=confidence),
            seeds=len(differences),
        ),
        dropped=returned_precision_drops(instances, first, second, k, **common) if paired else None,
    )


def summarize(
    instances: Sequence[QueryInstance],
    *,
    seed: int,
    budgets: Sequence[int] = DEFAULT_BUDGETS,
    comparisons: Sequence[tuple[ListName, ListName]] = DEFAULT_COMPARISONS,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    drop_unverified: bool = False,
) -> dict[str, object]:
    """Every §3.5 metric for every list and budget, overall and per class, as plain JSON data.

    Run it twice for a report: once as is, and once with ``drop_unverified=True`` for the
    sensitivity table of §3.4 (only ``S`` and ``F`` change). ``seed`` is required so every
    result records the bootstrap seed it was computed with.
    """
    instances = list(instances)
    validate_instances(instances)
    for k in budgets:
        _check_budget(k)
    classes = sorted({instance.query_class for instance in instances})
    options = {"seed": seed, "resamples": resamples, "confidence": confidence, "drop_unverified": drop_unverified}

    def block(query_class: str | None, k: int) -> dict[str, object]:
        lists = {
            name: {
                metric: estimate(instances, metric, name, k, query_class=query_class, **options).as_dict()
                for metric in METRICS
            }
            for name in LIST_NAMES
        }
        differences = {
            f"{first}-{second}": {
                metric: paired_difference(
                    instances, metric, first, second, k, query_class=query_class, **options
                ).as_dict()
                for metric in METRICS
            }
            for first, second in comparisons
        }
        return {"lists": lists, "differences": differences}

    seeds = {instance.seed_id for instance in instances}
    positive_seeds = {instance.seed_id for instance in instances if instance.positive}
    zero_relevant_seeds = {instance.seed_id for instance in instances if not instance.positive}
    return {
        "settings": {
            "budgets": list(budgets),
            "comparisons": [f"{first}-{second}" for first, second in comparisons],
            "seed": seed,
            "resamples": resamples,
            "confidence": confidence,
            "drop_unverified": drop_unverified,
        },
        "counts": {
            "instances": len(instances),
            "seeds": len(seeds),
            "seeds_with_a_positive_variant": len(positive_seeds),
            "seeds_with_a_zero_relevant_variant": len(zero_relevant_seeds),
            "duplicate_keys_in_pools": sum(
                len(instance.pool) - len({candidate.key for candidate in instance.pool}) for instance in instances
            ),
            "classes": {
                query_class: len({i.seed_id for i in instances if i.query_class == query_class})
                for query_class in classes
            },
        },
        "budgets": {
            str(k): {
                "boundary_ties": sum(boundary_tie(instance.pool, k) for instance in instances),
                "overall": block(None, k),
                "by_class": {query_class: block(query_class, k) for query_class in classes},
            }
            for k in budgets
        },
    }
