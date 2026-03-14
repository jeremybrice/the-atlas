from click.testing import CliRunner
from atlas.cli import main


def test_vault_group_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "--help"])
    assert result.exit_code == 0
    assert "Manage the credential vault" in result.output


def test_vault_list_no_credentials(tmp_path, monkeypatch):
    """Vault list should report no credentials when the DB doesn't exist."""
    # Isolate from real ~/.atlas by pointing _ensure_data_dir to tmp_path
    fake_data_dir = tmp_path / ".atlas"
    fake_data_dir.mkdir()
    (fake_data_dir / "data").mkdir()
    monkeypatch.setattr("atlas.cli._ensure_data_dir", lambda: fake_data_dir)

    runner = CliRunner()
    result = runner.invoke(main, ["vault", "list"])
    assert result.exit_code == 0
