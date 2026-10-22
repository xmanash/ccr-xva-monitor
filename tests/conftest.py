import pytest

from ccr_xva.memory.repository import clear_repository_cache, get_repository
from ccr_xva.services.risk import RiskService
from ccr_xva.utils.paths import repo_root
from shared.settings import get_settings


@pytest.fixture
def service(tmp_path, monkeypatch):
    database = tmp_path / "test.db"
    monkeypatch.setenv("CCR_DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("CCR_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    monkeypatch.setenv("CCR_ROOT", str(repo_root()))
    get_settings.cache_clear()
    clear_repository_cache()
    settings = get_settings()
    return RiskService(get_repository(settings.database_url), settings)
