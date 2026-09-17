import pytest

import config


def write(tmp_path, text):
    (tmp_path / ".github").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github" / "buildwork.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_no_file_is_fatal(tmp_path):
    with pytest.raises(config.ConfigError, match="opt-in"):
        config.load(tmp_path)


def test_enabled_false_does_nothing(tmp_path):
    """The gate. A config that exists but is not armed must not arm the skill."""
    write(tmp_path, "enabled = false\n")
    with pytest.raises(config.ConfigError, match="enabled = true"):
        config.load(tmp_path)


def test_enabled_missing_does_nothing(tmp_path):
    write(tmp_path, 'runner = "paseo"\n')
    with pytest.raises(config.ConfigError, match="enabled = true"):
        config.load(tmp_path)


def test_enabled_truthy_string_is_not_true(tmp_path):
    """`enabled = "yes"` is a half-written file, not consent."""
    write(tmp_path, 'enabled = "yes"\n')
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_bad_toml_names_the_file(tmp_path):
    write(tmp_path, "enabled = true\nthis is not toml\n")
    with pytest.raises(config.ConfigError, match="not valid TOML"):
        config.load(tmp_path)


def test_unknown_runner_rejected(tmp_path):
    write(tmp_path, 'enabled = true\nrunner = "kubernetes"\n')
    with pytest.raises(config.ConfigError, match="runner"):
        config.load(tmp_path)


def test_defaults(tmp_path):
    write(tmp_path, "enabled = true\n")
    cfg = config.load(tmp_path)
    assert cfg.runner == "auto"
    assert cfg.roadmap == "roadmap.md"
    assert cfg.base == "main"
    assert cfg.gate is None
    assert cfg.hotspots == ()
    assert cfg.wave_max == 4


def test_full_config(tmp_path):
    write(tmp_path, """
enabled = true
runner = "paseo"
roadmap = "ROADMAP.md"
base = "trunk"
gate = "make test"
hotspots = ["src/routes.ts", "public/_headers"]
digest = ["AGENTS.md"]

[wave]
max = 3
""")
    cfg = config.load(tmp_path)
    assert cfg.runner == "paseo"
    assert cfg.base == "trunk"
    assert cfg.gate == "make test"
    assert cfg.hotspots == ("src/routes.ts", "public/_headers")
    assert cfg.digest == ("AGENTS.md",)
    assert cfg.wave_max == 3
    assert cfg.roadmap_path == tmp_path / "ROADMAP.md"


def test_wave_max_must_be_positive(tmp_path):
    write(tmp_path, "enabled = true\n\n[wave]\nmax = 0\n")
    with pytest.raises(config.ConfigError, match="at least 1"):
        config.load(tmp_path)


def test_hotspots_must_be_strings(tmp_path):
    write(tmp_path, "enabled = true\nhotspots = [1, 2]\n")
    with pytest.raises(config.ConfigError, match="hotspots"):
        config.load(tmp_path)


def test_config_can_only_tighten_the_runner_cap(tmp_path):
    """A subagent runner caps at 2 however large the config's number is."""
    write(tmp_path, "enabled = true\n\n[wave]\nmax = 12\n")
    cfg = config.load(tmp_path)
    assert cfg.cap_for("subagent") == 2
    assert cfg.cap_for("paseo") == 4


def test_config_can_lower_below_the_runner_cap(tmp_path):
    write(tmp_path, "enabled = true\n\n[wave]\nmax = 1\n")
    cfg = config.load(tmp_path)
    assert cfg.cap_for("paseo") == 1


def test_starter_is_never_armed(tmp_path):
    """Parsed, not grepped: the template explains the gate in a comment, and a
    naive string search for `enabled = true` would find the explanation."""
    text = config.starter(base="main", hotspots=["a/b.ts"], digest=["AGENTS.md"])
    assert '"a/b.ts"' in text
    write(tmp_path, text)
    with pytest.raises(config.ConfigError, match="enabled = true"):
        config.load(tmp_path)


def test_starter_becomes_valid_once_armed(tmp_path):
    text = config.starter(base="trunk", hotspots=["a/b.ts"], digest=["AGENTS.md"])
    write(tmp_path, text.replace("enabled = false", "enabled = true"))
    cfg = config.load(tmp_path)
    assert cfg.base == "trunk"
    assert cfg.hotspots == ("a/b.ts",)
    assert cfg.digest == ("AGENTS.md",)
