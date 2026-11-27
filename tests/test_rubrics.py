import pytest

from s1evals.rubrics import Kind, parse

BASE = {
    "id": "x", "version": 1, "source": "test", "question": "Q?", "evidence": "e",
    "labels": {"a": "A", "b": "B"},
}  # fmt: skip


def test_rubric_folder_loads_all_twelve(rubrics):
    assert len(rubrics) == 12
    assert {r.source for r in rubrics.values()} == {"design-doc", "judgment-labs-blog"}


def test_noul_labels_are_strings_not_yaml_booleans(rubrics):
    for r in rubrics.values():
        if r.kind is Kind.NOUL:
            assert set(r.labels) == {"yes", "no"}


def test_code_only_label_is_offered_to_agent_not_model(rubrics):
    r = rubrics["destructive_without_confirmation"]
    assert "n/a" not in r.labels
    assert r.all_labels == ["yes", "no", "n/a"]


def test_noul_requires_yes_no():
    with pytest.raises(ValueError, match="yes/no"):
        parse({**BASE, "kind": "noul"})


def test_judge_version_changes_with_rubric_version():
    assert parse(BASE).judge_version("jev", "m") != parse({**BASE, "version": 2}).judge_version("jev", "m")
