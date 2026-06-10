"""Tests for config.settings environment handling."""



def test_get_env_value_prefers_environment(monkeypatch, tmp_path):
    import config.settings as settings

    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("TUSHARE_TOKEN=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("TUSHARE_TOKEN", "from_env")

    assert settings.get_tushare_token() == "from_env"


def test_get_env_value_reads_project_dotenv(monkeypatch, tmp_path):
    import config.settings as settings

    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text('TUSHARE_TOKEN="from_dotenv"\n', encoding="utf-8")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    assert settings.get_env_value("TUSHARE_TOKEN") == "from_dotenv"
