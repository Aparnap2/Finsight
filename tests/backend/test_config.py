from backend.config import get_settings


def test_settings_loads_default_postgres_uri():
    settings = get_settings()
    assert "postgresql" in settings.postgres_uri


def test_settings_loads_qdrant_url():
    settings = get_settings()
    assert settings.qdrant_url is not None


def test_settings_loads_redis_url():
    settings = get_settings()
    assert "redis" in settings.redis_url
