from click.testing import CliRunner
from atlas.cli import main


def test_vault_group_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "--help"])
    assert result.exit_code == 0
    assert "Manage the credential vault" in result.output


def test_vault_list_no_credentials():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "list"])
    assert result.exit_code == 0
