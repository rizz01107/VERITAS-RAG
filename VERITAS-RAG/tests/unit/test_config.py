from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.core.config import (
    ENV_GENERATOR_API_KEY,
    deep_merge,
    env_overrides,
    load_secrets,
    load_settings,
    require_secret,
)
from app.core.errors import ConfigError

pytestmark = pytest.mark.unit
Writer = Callable[[str, dict[str, Any]], Path]


def test_default_config_loads_and_hash_is_stable(repo_root: Path) -> None:
    a = load_settings(environ={}, root=repo_root)
    b = load_settings(environ={}, root=repo_root)
    assert a.config_hash() == b.config_hash()
    assert len(a.config_hash()) == 64
    assert a.run.mode == "dev"


@pytest.mark.parametrize("name", ["dev_cpu.yaml", "eval_full.yaml"])
def test_profile_configs_load(repo_root: Path, name: str) -> None:
    settings = load_settings(repo_root / "configs" / name, environ={})
    assert settings.run.mode in {"dev", "full"}


def test_profiles_differ_from_default(repo_root: Path) -> None:
    default = load_settings(environ={}, root=repo_root)
    full = load_settings(repo_root / "configs/eval_full.yaml", environ={})
    assert full.config_hash() != default.config_hash()
    assert full.budget.max_llm_calls is None


def test_hash_independent_of_key_order(write_yaml: Writer) -> None:
    a = write_yaml("a.yaml", {"retrieval": {"top_k": 7, "candidate_k": 40}, "run": {"seed": 1}})
    b = write_yaml("b.yaml", {"run": {"seed": 1}, "retrieval": {"candidate_k": 40, "top_k": 7}})
    assert load_settings(a, {}).config_hash() == load_settings(b, {}).config_hash()


def test_env_override_changes_value_and_hash(repo_root: Path) -> None:
    base = load_settings(environ={}, root=repo_root)
    over = load_settings(environ={"VERITAS_RETRIEVAL__TOP_K": "7"}, root=repo_root)
    assert over.retrieval.top_k == 7
    assert over.config_hash() != base.config_hash()


def test_env_list_and_bool_parsing() -> None:
    parsed = env_overrides(
        {"VERITAS_INGESTION__ALLOWED_EXTENSIONS": "[.pdf]", "VERITAS_EMBEDDING__NORMALIZE": "false"}
    )
    assert parsed["embedding"]["normalize"] is False
    assert parsed["ingestion"]["allowed_extensions"] == [".pdf"]


def test_secrets_do_not_affect_config_hash(repo_root: Path) -> None:
    a = load_settings(environ={}, root=repo_root)
    b = load_settings(environ={ENV_GENERATOR_API_KEY: "sk-test-secret-value"}, root=repo_root)
    assert a.config_hash() == b.config_hash()


def test_paths_serialise_posix(repo_root: Path) -> None:
    dumped = load_settings(environ={}, root=repo_root).canonical_dict()
    assert "\\" not in str(dumped["paths"])


def test_deep_merge_does_not_mutate() -> None:
    base = {"a": {"b": 1, "c": 2}}
    merged = deep_merge(base, {"a": {"b": 9}})
    assert merged == {"a": {"b": 9, "c": 2}}
    assert base == {"a": {"b": 1, "c": 2}}


def test_extends_chain(write_yaml: Writer, tmp_path: Path) -> None:
    write_yaml("parent.yaml", {"retrieval": {"top_k": 9, "candidate_k": 50}})
    child = write_yaml("child.yaml", {"extends": "parent.yaml", "retrieval": {"top_k": 3}})
    settings = load_settings(child, {})
    assert (settings.retrieval.top_k, settings.retrieval.candidate_k) == (3, 50)


def test_secrets_repr_hides_value() -> None:
    secrets = load_secrets({ENV_GENERATOR_API_KEY: "sk-very-secret-12345"})
    assert "very-secret" not in repr(secrets)
    assert (
        require_secret(secrets.generator_api_key, ENV_GENERATOR_API_KEY) == "sk-very-secret-12345"
    )


def test_empty_secret_counts_as_unset() -> None:
    assert load_secrets({ENV_GENERATOR_API_KEY: ""}).generator_api_key is None


# ---- failure cases -----------------------------------------------------------------
edge = pytest.mark.edge


@edge
def test_missing_secret_names_variable_not_value() -> None:
    with pytest.raises(ConfigError) as info:
        require_secret(load_secrets({}).generator_api_key, ENV_GENERATOR_API_KEY)
    assert ENV_GENERATOR_API_KEY in str(info.value)


@edge
def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_settings(tmp_path / "nope.yaml", {})


@edge
def test_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_settings(bad, {})


@edge
def test_root_must_be_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings(bad, {})


@edge
def test_unknown_key_in_yaml_rejected(write_yaml: Writer) -> None:
    with pytest.raises(ConfigError, match="retreival|Extra"):
        load_settings(write_yaml("x.yaml", {"retreival": {"top_k": 3}}), {})


@edge
def test_unknown_env_nested_path_rejected(repo_root: Path) -> None:
    with pytest.raises(ConfigError, match="retrieval.top_kk"):
        load_settings(environ={"VERITAS_RETRIEVAL__TOP_KK": "3"}, root=repo_root)


@edge
def test_wrong_type_env_rejected(repo_root: Path) -> None:
    with pytest.raises(ConfigError, match="top_k"):
        load_settings(environ={"VERITAS_RETRIEVAL__TOP_K": "abc"}, root=repo_root)


@edge
@pytest.mark.parametrize(
    ("section", "values", "needle"),
    [
        ("chunking", {"chunk_size": 64, "chunk_overlap": 64}, "chunk_overlap"),
        ("retrieval", {"top_k": 10, "candidate_k": 5}, "candidate_k"),
        ("retrieval", {"top_k": 0}, "top_k"),
        ("generation", {"temperature": 5}, "temperature"),
        ("ingestion", {"allowed_extensions": ["pdf"]}, "allowed_extensions"),
        ("run", {"mode": "prod"}, "mode"),
    ],
)
def test_invalid_values_rejected(
    write_yaml: Writer, section: str, values: dict[str, Any], needle: str
) -> None:
    with pytest.raises(ConfigError, match=needle):
        load_settings(write_yaml("v.yaml", {section: values}), {})


@edge
def test_cyclic_extends(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cyclic"):
        load_settings(tmp_path / "a.yaml", {})


@edge
def test_malformed_override_name(repo_root: Path) -> None:
    with pytest.raises(ConfigError, match="malformed"):
        load_settings(environ={"VERITAS_RETRIEVAL____TOP_K": "3"}, root=repo_root)


@edge
def test_unrecognised_env_var_warns_not_fails(
    repo_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="veritas.config"):
        load_settings(environ={"VERITAS_TYPO": "1"}, root=repo_root)
    assert "VERITAS_TYPO" in caplog.text
