from pathlib import Path

import pytest

from fbw_harness.config import HarnessConfig, load_config
from fbw_harness.errors import InputError
from fbw_harness.models import RunRequest


def write_toml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def make_request(
    *, config_path: Path | None = None, overrides: dict[str, object] | None = None
) -> RunRequest:
    return RunRequest(
        workspace=Path("project"),
        task="fix tests",
        base_url="https://example.test/v1",
        model="model",
        config_path=config_path,
        config_overrides=overrides or {},
    )


def test_config_priority_is_cli_project_user_default(tmp_path: Path) -> None:
    user = write_toml(tmp_path / "user.toml", "max_rounds = 4\n")
    project = write_toml(tmp_path / "project.toml", "max_rounds = 5\n")
    request = make_request(config_path=project, overrides={"max_rounds": 6})
    assert load_config(request, user_config=user).max_rounds == 6


@pytest.mark.parametrize("name", ["api_key", "authorization", "secret"])
def test_config_rejects_secret_fields(tmp_path: Path, name: str) -> None:
    config = write_toml(tmp_path / "bad.toml", f'{name} = "value"\n')
    with pytest.raises(InputError, match="secret"):
        load_config(make_request(config_path=config), user_config=None)


def test_config_uses_defaults_when_no_source_sets_a_value() -> None:
    assert load_config(make_request(), user_config=None) == HarnessConfig()


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [
        ("CLI", "unknown", {"unknown": 1}),
        ("project", "unknown", "unknown = 1\n"),
        ("user", "unknown", "unknown = 1\n"),
    ],
)
def test_config_rejects_unknown_field_with_source_and_without_value(
    tmp_path: Path, source: str, field: str, value: object
) -> None:
    hidden_value = "do-not-disclose"
    if source == "CLI":
        request = make_request(overrides={field: hidden_value})
        user_config = None
    else:
        config = write_toml(tmp_path / f"{source}.toml", str(value))
        request = make_request(config_path=config if source == "project" else None)
        user_config = config if source == "user" else None

    with pytest.raises(InputError) as error:
        load_config(request, user_config=user_config)

    message = str(error.value)
    assert source in message
    assert field in message
    assert hidden_value not in message


@pytest.mark.parametrize("value", [0, -1, True, "6"])
def test_config_rejects_non_positive_or_non_integer_budget(value: object) -> None:
    with pytest.raises(InputError) as error:
        load_config(make_request(overrides={"max_rounds": value}), user_config=None)

    assert "CLI" in str(error.value)
    assert "max_rounds" in str(error.value)
    assert str(value) not in str(error.value)


@pytest.mark.parametrize("argument", ["--rootdir=other", "-cpytest.ini", "x;y", "x|y", "x&y", "x\ny"])
def test_config_rejects_unsafe_pytest_argument(argument: str) -> None:
    with pytest.raises(InputError) as error:
        load_config(make_request(overrides={"pytest_args": [argument]}), user_config=None)

    assert "CLI" in str(error.value)
    assert "pytest_args" in str(error.value)
    assert argument not in str(error.value)


def test_config_accepts_declared_types_and_normalizes_paths() -> None:
    result = load_config(
        make_request(
            overrides={
                "max_rounds": 7,
                "api_retries": 3,
                "pytest_timeout_seconds": 30,
                "repeat_limit": 4,
                "file_size_limit_bytes": 1024,
                "normal_change_line_limit": 50,
                "output_tail_chars": 500,
                "pytest_args": ["-q", "tests"],
                "jsonl_log": "logs/run.jsonl",
                "memory_enabled": True,
                "memory_path": "memory.json",
            }
        ),
        user_config=None,
    )

    assert result.max_rounds == 7
    assert result.api_retries == 3
    assert result.pytest_timeout_seconds == 30
    assert result.repeat_limit == 4
    assert result.file_size_limit_bytes == 1024
    assert result.normal_change_line_limit == 50
    assert result.output_tail_chars == 500
    assert result.pytest_args == ("-q", "tests")
    assert result.jsonl_log == Path("logs/run.jsonl")
    assert result.memory_enabled is True
    assert result.memory_path == Path("memory.json")


@pytest.mark.parametrize("source", ["project", "user"])
def test_config_rejects_non_utf8_file_without_disclosing_path_or_content(
    tmp_path: Path, source: str
) -> None:
    config = tmp_path / f"{source}.toml"
    config.write_bytes(b"\xffprivate-content")
    request = make_request(config_path=config if source == "project" else None)

    with pytest.raises(InputError) as error:
        load_config(request, user_config=config if source == "user" else None)

    message = str(error.value)
    assert source in message
    assert "config_file" in message
    assert str(config) not in message
    assert "private-content" not in message


@pytest.mark.parametrize(
    ("source", "contents"),
    [
        ("project", None),
        ("user", None),
        ("project", "max_rounds =\n"),
        ("user", "max_rounds =\n"),
    ],
)
def test_config_file_errors_identify_source_and_config_file(
    tmp_path: Path, source: str, contents: str | None
) -> None:
    config = tmp_path / f"{source}.toml"
    if contents is not None:
        write_toml(config, contents)
    request = make_request(config_path=config if source == "project" else None)

    with pytest.raises(InputError) as error:
        load_config(request, user_config=config if source == "user" else None)

    message = str(error.value)
    assert source in message
    assert "config_file" in message
    assert str(config) not in message
    assert "max_rounds" not in message


@pytest.mark.parametrize("source", ["CLI", "project", "user"])
def test_config_rejects_pytest_at_file_argument_from_every_source(
    tmp_path: Path, source: str
) -> None:
    config = write_toml(tmp_path / f"{source}.toml", 'pytest_args = ["@options.txt"]\n')
    request = make_request(
        config_path=config if source == "project" else None,
        overrides={"pytest_args": ["@options.txt"]} if source == "CLI" else None,
    )

    with pytest.raises(InputError) as error:
        load_config(request, user_config=config if source == "user" else None)

    message = str(error.value)
    assert source in message
    assert "pytest_args" in message
    assert "@options.txt" not in message
