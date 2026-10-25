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

"""Hermetic tests for retrieval_metrics: the lists, metrics and edge cases of eval.md §3.4-3.5."""

from __future__ import annotations

import json
import math
import random

import pytest

import retrieval_metrics as rm
from retrieval_metrics import Candidate, QueryInstance

RESAMPLES = 500


def c(key: str, verdict: str = "confirmed", similarity: float | None = None) -> Candidate:
    return Candidate(key=key, similarity=0.5 if similarity is None else similarity, verdict=verdict)


def pool(*spec: str) -> tuple[Candidate, ...]:
    """``"a"`` confirmed, ``"a!"`` rejected, ``"a?"`` unverified; similarity falls with rank."""
    verdicts = {"!": "rejected", "?": "unverified"}
    return tuple(
        Candidate(key=s.rstrip("!?"), similarity=1 - i / 100, verdict=verdicts.get(s[-1], "confirmed"))
        for i, s in enumerate(spec)
    )


def q(seed, variant="v0", repeat=0, query_class="instrument", candidates=(), relevant=()) -> QueryInstance:
    return QueryInstance(
        seed_id=seed,
        variant_id=variant,
        repeat=repeat,
        query_class=query_class,
        pool=tuple(candidates),
        relevant=frozenset(relevant),
    )


# --- §3.4 lists ---------------------------------------------------------------------------


class TestCutList:
    C = pool("a", "b!", "c?", "d", "e!", "f", "g")

    def keys(self, items):
        return [item.key for item in items]

    def test_baseline_is_the_pool_prefix(self):
        assert self.keys(rm.cut_list(self.C, "B", 3)) == ["a", "b", "c"]

    def test_post_filter_drops_rejected_from_the_prefix_and_keeps_order(self):
        assert self.keys(rm.cut_list(self.C, "S", 3)) == ["a", "c"]

    def test_fill_to_k_takes_the_first_k_survivors_of_the_whole_pool(self):
        assert self.keys(rm.cut_list(self.C, "F", 3)) == ["a", "c", "d"]
        assert self.keys(rm.cut_list(self.C, "F", 5)) == ["a", "c", "d", "f", "g"]

    def test_unverified_is_kept_unless_the_sensitivity_variant_drops_it(self):
        assert self.keys(rm.cut_list(self.C, "S", 3, drop_unverified=True)) == ["a"]
        assert self.keys(rm.cut_list(self.C, "F", 3, drop_unverified=True)) == ["a", "d", "f"]
        assert self.keys(rm.cut_list(self.C, "B", 3, drop_unverified=True)) == ["a", "b", "c"]

    def test_fewer_than_k_candidates_gives_short_lists(self):
        short = pool("a", "b!")
        assert self.keys(rm.cut_list(short, "B", 5)) == ["a", "b"]
        assert self.keys(rm.cut_list(short, "S", 5)) == ["a"]
        assert self.keys(rm.cut_list(short, "F", 5)) == ["a"]  # pool exhaustion
        assert rm.cut_list((), "F", 3) == ()

    def test_tied_candidates_keep_their_returned_order(self):
        tied = (c("z", similarity=0.7), c("a", similarity=0.7), c("m", similarity=0.9))
        assert self.keys(rm.cut_list(tied, "B", 3)) == ["z", "a", "m"]

    @pytest.mark.parametrize("k", [0, -1, 1.5, True])
    def test_a_budget_must_be_a_positive_integer(self, k):
        with pytest.raises(ValueError, match="budget"):
            rm.cut_list(self.C, "B", k)

    def test_an_unknown_list_is_an_error(self):
        with pytest.raises(ValueError, match="list_name"):
            rm.cut_list(self.C, "X", 3)


def test_candidates_reject_unknown_verdicts_and_non_finite_scores():
    with pytest.raises(ValueError, match="verdict"):
        Candidate(key="a", similarity=0.5, verdict="maybe")
    with pytest.raises(ValueError, match="similarity"):
        Candidate(key="a", similarity=math.nan, verdict="confirmed")


def test_boundary_ties_compare_positions_k_and_k_plus_one_exactly():
    tied = (c("a", similarity=0.9), c("b", similarity=0.8), c("c", similarity=0.8), c("d", similarity=0.1))
    assert rm.boundary_tie(tied, 2) is True
    assert rm.boundary_tie(tied, 1) is False
    assert rm.boundary_tie(tied, 3) is False
    assert rm.boundary_tie(tied, 4) is False  # no K+1 position


# --- §3.5 per-instance metrics -----------------------------------------------------------


class TestListMetrics:
    def test_standard_and_returned_precision_recall_f1_mrr_coverage(self):
        m = rm.list_metrics(pool("x", "a", "y", "b"), {"a", "b", "c"}, 5)
        assert (m.length, m.hits) == (4, 2)
        assert m.standard_precision == pytest.approx(2 / 5)  # the empty fifth slot is a miss
        assert m.returned_precision == pytest.approx(2 / 4)
        assert m.recall == pytest.approx(2 / 3)
        p, r = 2 / 5, 2 / 3
        assert m.f1 == pytest.approx(2 * p * r / (p + r))
        assert m.mrr == pytest.approx(1 / 2)
        assert m.coverage == pytest.approx(4 / 5)
        assert (m.false_positives, m.empty) == (2.0, 0.0)
        assert m.zero_relevant_length is None and m.zero_relevant_nonempty is None

    def test_no_relevant_hit_gives_zero_f1_and_mrr(self):
        m = rm.list_metrics(pool("x", "y"), {"a"}, 3)
        assert (m.standard_precision, m.recall, m.f1, m.mrr, m.returned_precision) == (0.0, 0.0, 0.0, 0.0, 0.0)

    def test_an_empty_list_has_no_returned_precision_but_full_coverage_signal(self):
        m = rm.list_metrics((), {"a"}, 3)
        assert m.returned_precision is None
        assert (m.standard_precision, m.recall, m.f1, m.mrr) == (0.0, 0.0, 0.0, 0.0)
        assert (m.coverage, m.empty, m.false_positives) == (0.0, 1.0, 0.0)

    def test_an_empty_relevant_set_is_a_zero_relevant_query(self):
        m = rm.list_metrics(pool("x", "y"), set(), 3)
        for metric in rm.POSITIVE_METRICS:
            assert m.value(metric) is None, metric
        assert (m.zero_relevant_length, m.zero_relevant_nonempty) == (2.0, 1.0)
        assert m.coverage == pytest.approx(2 / 3)
        empty = rm.list_metrics((), set(), 3)
        assert (empty.zero_relevant_length, empty.zero_relevant_nonempty, empty.empty) == (0.0, 0.0, 1.0)

    def test_a_duplicate_key_takes_a_slot_but_is_never_a_second_hit(self):
        m = rm.list_metrics(pool("a", "a", "b"), {"a"}, 3)
        assert (m.length, m.hits, m.duplicates) == (3, 1, 1)
        assert m.standard_precision == pytest.approx(1 / 3)
        assert m.returned_precision == pytest.approx(1 / 3)
        assert m.recall == 1.0
        assert m.false_positives == 2.0
        assert m.coverage == 1.0

    def test_a_duplicate_before_the_first_relevant_item_moves_its_position(self):
        assert rm.list_metrics(pool("x", "x", "a"), {"a"}, 3).mrr == pytest.approx(1 / 3)

    def test_an_unknown_metric_is_an_error(self):
        with pytest.raises(ValueError, match="unknown metric"):
            rm.list_metrics((), {"a"}, 1).value("ndcg")


def test_post_filter_never_gains_hits_over_the_baseline():
    rng = random.Random(7)
    keys = [f"k{i}" for i in range(15)]
    for _ in range(200):
        candidates = tuple(
            Candidate(key=key, similarity=1.0, verdict=rng.choice(sorted(rm.VERDICTS)))
            for key in rng.sample(keys, rng.randint(0, 12))
        )
        relevant = set(rng.sample(keys, rng.randint(1, 5)))
        for k in rm.DEFAULT_BUDGETS:
            baseline = rm.list_metrics(rm.cut_list(candidates, "B", k), relevant, k)
            post = rm.list_metrics(rm.cut_list(candidates, "S", k), relevant, k)
            assert post.hits <= baseline.hits
            assert post.standard_precision <= baseline.standard_precision
            assert post.recall <= baseline.recall
            assert post.f1 <= baseline.f1


def test_rejecting_the_first_relevant_item_lowers_post_filter_mrr_and_rejecting_noise_raises_it():
    relevant = {"a"}
    noise_rejected = q("s", candidates=pool("x!", "a"), relevant=relevant)
    relevant_rejected = q("s", candidates=pool("a!", "x"), relevant=relevant)
    assert rm.instance_metrics(noise_rejected, "B", 2).mrr == 0.5
    assert rm.instance_metrics(noise_rejected, "S", 2).mrr == 1.0
    assert rm.instance_metrics(relevant_rejected, "B", 2).mrr == 1.0
    assert rm.instance_metrics(relevant_rejected, "S", 2).mrr == 0.0


# --- §3.5 aggregation --------------------------------------------------------------------


def test_repeats_then_variants_then_seeds_are_averaged_with_equal_weight():
    instances = [
        # seed s1: variant v0 hits in one of two repeats (0.5), variant v1 always (1.0) -> 0.75
        q("s1", "v0", 0, candidates=pool("a"), relevant={"a"}),
        q("s1", "v0", 1, candidates=pool("x"), relevant={"a"}),
        q("s1", "v1", 0, candidates=pool("a"), relevant={"a"}),
        # seed s2: one variant, one repeat, a miss -> 0.0
        q("s2", "v0", 0, candidates=pool("x"), relevant={"a"}),
    ]
    assert rm.seed_values(instances, "standard_precision", "B", 1) == {"s1": 0.75, "s2": 0.0}
    estimate = rm.estimate(instances, "standard_precision", "B", 1, seed=1, resamples=RESAMPLES)
    assert estimate.mean == pytest.approx(0.375)  # macro over seeds, not over the four instances
    assert estimate.seeds == 2


def test_zero_relevant_variants_only_feed_the_zero_relevant_metrics():
    instances = [
        q("s1", "v0", candidates=pool("a", "x"), relevant={"a"}),
        q("s1", "v1", candidates=pool("x", "y"), relevant=set()),  # a zero-relevant paraphrase
        q("neg", "v0", candidates=pool("x"), relevant=set()),  # a negative seed
        q("neg2", "v0", candidates=(), relevant=set()),  # a negative seed with nothing returned
    ]
    assert rm.seed_values(instances, "standard_precision", "B", 2) == {"s1": 0.5}
    assert rm.seed_values(instances, "mrr", "B", 2) == {"s1": 1.0}
    assert rm.seed_values(instances, "zero_relevant_length", "B", 2) == {"neg": 1.0, "neg2": 0.0, "s1": 2.0}
    assert rm.seed_values(instances, "zero_relevant_nonempty", "B", 2) == {"neg": 1.0, "neg2": 0.0, "s1": 1.0}
    # Coverage and the empty share use every instance.
    assert rm.seed_values(instances, "coverage", "B", 2) == {"neg": 0.5, "neg2": 0.0, "s1": 1.0}
    assert rm.seed_values(instances, "empty", "B", 2) == {"neg": 0.0, "neg2": 1.0, "s1": 0.0}


def test_returned_precision_comparisons_use_only_instances_where_both_lists_are_non_empty():
    instances = [
        q("s1", "v0", candidates=pool("a", "x"), relevant={"a"}),  # S and B non-empty
        q("s2", "v0", candidates=pool("x!", "y!"), relevant={"a"}),  # S empty, B not
        q("s3", "v0", repeat=0, candidates=pool("x!"), relevant={"a"}),  # S empty in one repeat
        q("s3", "v0", repeat=1, candidates=pool("a", "x!"), relevant={"a"}),
        q("s4", "v0", candidates=pool("x"), relevant=set()),  # zero-relevant: not a returned-precision instance
    ]
    diff = rm.paired_difference(instances, "returned_precision", "S", "B", 2, seed=3, resamples=RESAMPLES)
    assert diff.dropped == {"first_empty": 2, "second_empty": 0, "both_empty": 0}
    # s1: S 1/2 - B 1/2 = 0; s3 (repeat 1 only): S 1/1 - B 1/2 = 0.5; s2 has no shared instance.
    assert diff.estimate.seeds == 2
    assert diff.estimate.mean == pytest.approx(0.25)
    # On its own, each list's returned precision uses its own non-empty instances: B has both
    # s3 repeats (0 and 1/2), while the S-B comparison above kept only repeat 1.
    assert rm.seed_values(instances, "returned_precision", "B", 2)["s3"] == pytest.approx(0.25)
    assert "s2" not in rm.seed_values(instances, "returned_precision", "S", 2)


def test_returned_precision_drops_count_both_empty_lists():
    instances = [q("s1", candidates=(), relevant={"a"})]
    assert rm.returned_precision_drops(instances, "S", "B", 3) == {
        "first_empty": 0,
        "second_empty": 0,
        "both_empty": 1,
    }


def test_per_class_values_use_only_that_class():
    instances = [
        q("s1", query_class="instrument", candidates=pool("a"), relevant={"a"}),
        q("s2", query_class="entity", candidates=pool("x"), relevant={"a"}),
    ]
    assert rm.seed_values(instances, "recall", "B", 1, query_class="instrument") == {"s1": 1.0}
    assert rm.seed_values(instances, "recall", "B", 1, query_class="entity") == {"s2": 0.0}


class TestValidation:
    def test_a_repeated_instance_is_rejected(self):
        with pytest.raises(ValueError, match="more than once"):
            rm.validate_instances([q("s1"), q("s1")])

    def test_a_seed_with_two_classes_is_rejected(self):
        with pytest.raises(ValueError, match="more than one class"):
            rm.validate_instances([q("s1", "v0", query_class="asset"), q("s1", "v1", query_class="entity")])

    def test_a_variant_whose_labels_change_between_repeats_is_rejected(self):
        with pytest.raises(ValueError, match="relevant sets"):
            rm.validate_instances([q("s1", repeat=0, relevant={"a"}), q("s1", repeat=1, relevant={"b"})])

    def test_a_pool_must_hold_candidates(self):
        with pytest.raises(TypeError, match="Candidate"):
            q("s1", candidates=[("a", 0.5, "confirmed")])


# --- §3.5 uncertainty --------------------------------------------------------------------


class TestBootstrap:
    def test_no_values_gives_no_interval(self):
        assert rm.bootstrap_interval([], seed=1, resamples=RESAMPLES) is None

    def test_a_constant_gives_a_point_interval(self):
        assert rm.bootstrap_interval([0.4, 0.4, 0.4], seed=1, resamples=RESAMPLES) == pytest.approx((0.4, 0.4))

    def test_the_interval_brackets_the_mean(self):
        values = [0.0, 0.2, 0.4, 0.6, 1.0]
        low, high = rm.bootstrap_interval(values, seed=5, resamples=2_000)
        assert 0.0 <= low < sum(values) / len(values) < high <= 1.0

    def test_a_fixed_seed_reproduces_the_interval_and_another_seed_need_not(self):
        values = [0.1, 0.9, 0.3, 0.7, 0.5, 0.2]
        first = rm.bootstrap_interval(values, seed=42, resamples=RESAMPLES)
        assert first == rm.bootstrap_interval(values, seed=42, resamples=RESAMPLES)
        assert first != rm.bootstrap_interval(values, seed=43, resamples=RESAMPLES)

    @pytest.mark.parametrize(
        ("kwargs", "message"), [({"resamples": 0}, "resamples"), ({"confidence": 1.0}, "confidence")]
    )
    def test_invalid_settings_are_errors(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            rm.bootstrap_interval([0.5], seed=1, **{"resamples": RESAMPLES, **kwargs})


def test_a_paired_difference_resamples_whole_seeds_and_keeps_the_pairing():
    """Seeds differ in difficulty, but fill-to-K beats the baseline by exactly 0.5 P@2 on every seed.

    The paired bootstrap resamples per-seed differences, so its interval is the point [0.5, 0.5],
    while each list's own interval is wide because its level varies from seed to seed.
    """
    easier = pool("x!", "a", "b")  # B@2 = [x, a] -> 0.5; F@2 = [a, b] -> 1.0
    harder = pool("x!", "y", "a")  # B@2 = [x, y] -> 0.0; F@2 = [y, a] -> 0.5
    instances = [q(f"e{i}", candidates=easier, relevant={"a", "b"}) for i in range(4)]
    instances += [q(f"h{i}", candidates=harder, relevant={"a"}) for i in range(4)]

    diff = rm.paired_difference(instances, "standard_precision", "F", "B", 2, seed=9, resamples=RESAMPLES)
    assert diff.estimate.mean == pytest.approx(0.5)
    assert diff.estimate.interval == (0.5, 0.5)
    assert diff.estimate.seeds == 8

    for name in ("B", "F"):
        low, high = rm.estimate(instances, "standard_precision", name, 2, seed=9, resamples=RESAMPLES).interval
        assert high - low >= 0.25, name


def test_a_paired_difference_uses_only_seeds_with_a_value_on_both_sides():
    instances = [
        q("pos", candidates=pool("a!", "b"), relevant={"a"}),
        q("neg", candidates=pool("x"), relevant=set()),
    ]
    diff = rm.paired_difference(instances, "recall", "S", "B", 1, seed=1, resamples=RESAMPLES)
    assert diff.estimate.seeds == 1
    assert diff.estimate.mean == pytest.approx(-1.0)  # the critic rejected the only relevant item: recall cost


def test_identical_lists_have_a_zero_difference():
    instances = [q(f"s{i}", candidates=pool("a", "x"), relevant={"a"}) for i in range(5)]
    diff = rm.paired_difference(instances, "mrr", "S", "B", 2, seed=1, resamples=RESAMPLES)
    assert (diff.estimate.mean, diff.estimate.interval, diff.dropped) == (0.0, (0.0, 0.0), None)


# --- summary -----------------------------------------------------------------------------


def _corpus(seed: int = 11) -> list[QueryInstance]:
    """A synthetic labelled run: 12 seeds in 3 classes, 2 variants, 3 repeats, a few negatives."""
    rng = random.Random(seed)
    keys = [f"item{i}" for i in range(30)]
    instances = []
    for s in range(12):
        query_class = ("instrument", "entity", "negative")[s % 3]
        for v in range(2):
            relevant = set() if query_class == "negative" else set(rng.sample(keys, rng.randint(1, 4)))
            for r in range(3):
                candidates = tuple(
                    Candidate(key=key, similarity=round(1 - j * 0.03, 2), verdict=rng.choice(sorted(rm.VERDICTS)))
                    for j, key in enumerate(rng.sample(keys, rng.randint(0, 20)))
                )
                instances.append(q(f"seed{s}", f"v{v}", r, query_class, candidates, relevant))
    return instances


def test_summary_is_json_data_with_every_metric_list_budget_and_class():
    summary = rm.summarize(_corpus(), seed=2026, resamples=200)
    json.dumps(summary)  # plain data
    assert summary["settings"]["seed"] == 2026
    assert summary["counts"]["seeds"] == 12
    assert summary["counts"]["classes"] == {"entity": 4, "instrument": 4, "negative": 4}
    assert set(summary["budgets"]) == {"1", "3", "5", "10"}
    budget = summary["budgets"]["5"]
    for scope in [budget["overall"], *budget["by_class"].values()]:
        assert set(scope["lists"]) == {"B", "S", "F"}
        assert set(scope["differences"]) == {"S-B", "F-B"}
        for metrics in scope["lists"].values():
            assert set(metrics) == set(rm.METRICS)
    assert "dropped" in budget["overall"]["differences"]["S-B"]["returned_precision"]
    negative = budget["by_class"]["negative"]["lists"]["B"]
    assert negative["standard_precision"] == {"mean": None, "ci": None, "seeds": 0}
    assert negative["zero_relevant_nonempty"]["seeds"] == 4


def test_summary_is_reproducible_and_independent_of_input_order():
    instances = _corpus()
    first = rm.summarize(instances, seed=7, budgets=(3,), resamples=200)
    shuffled = list(instances)
    random.Random(1).shuffle(shuffled)
    assert rm.summarize(shuffled, seed=7, budgets=(3,), resamples=200) == first
    assert rm.summarize(instances, seed=8, budgets=(3,), resamples=200) != first


def test_summary_sensitivity_variant_changes_only_the_filtered_lists():
    instances = _corpus()
    kept = rm.summarize(instances, seed=7, budgets=(5,), resamples=200)["budgets"]["5"]["overall"]["lists"]
    dropped = rm.summarize(instances, seed=7, budgets=(5,), resamples=200, drop_unverified=True)["budgets"]["5"][
        "overall"
    ]["lists"]
    assert dropped["B"] == kept["B"]
    assert dropped["S"]["coverage"]["mean"] < kept["S"]["coverage"]["mean"]


def test_summary_counts_boundary_ties_and_duplicate_keys():
    instances = [
        q("s1", candidates=(c("a", similarity=0.9), c("b", similarity=0.9), c("a", similarity=0.8)), relevant={"a"})
    ]
    summary = rm.summarize(instances, seed=1, budgets=(1, 2), resamples=50)
    assert summary["budgets"]["1"]["boundary_ties"] == 1
    assert summary["budgets"]["2"]["boundary_ties"] == 0
    assert summary["counts"]["duplicate_keys_in_pools"] == 1


def test_summary_validates_its_input():
    with pytest.raises(ValueError, match="more than once"):
        rm.summarize([q("s1"), q("s1")], seed=1, resamples=10)
    with pytest.raises(ValueError, match="budget"):
        rm.summarize([q("s1")], seed=1, budgets=(0,), resamples=10)
