from app.services import model_config_service as service


def test_api_key_encryption_round_trip() -> None:
    encrypted = service.encrypt_api_key("sk-secret-value")
    assert encrypted != "sk-secret-value"
    assert service.decrypt_api_key(encrypted) == "sk-secret-value"


def test_api_key_decrypt_rejects_tampered_value() -> None:
    encrypted = service.encrypt_api_key("sk-secret-value")
    index = min(10, len(encrypted) - 1)
    flipped = encrypted[:index] + ("A" if encrypted[index] != "A" else "B") + encrypted[index + 1 :]
    assert service.decrypt_api_key(flipped) is None


def test_export_env_lines_returns_all_keys_in_order() -> None:
    lines = service.export_env_lines()
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == [
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "PRIMARY_LLM_MODEL",
        "PRIMARY_REVIEW_MODEL",
        "SECONDARY_REVIEW_MODEL",
        "EMBEDDING_MODEL",
    ]
    assert all("=" in line for line in lines)


def test_blank_database_values_keep_environment_fallback(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "openai_api_base", "https://env.example/v1")
    monkeypatch.setattr(service.settings, "primary_llm_model", "env-generation")
    monkeypatch.setattr(service.settings, "primary_review_model", "env-primary-review")
    monkeypatch.setattr(service.settings, "secondary_review_model", "env-secondary-review")
    monkeypatch.setattr(service.settings, "embedding_model", "env-embedding")

    service._apply({key: "" for key in service.EDITABLE_KEYS}, None)

    assert service.settings.openai_api_base == "https://env.example/v1"
    assert service.settings.primary_llm_model == "env-generation"
    assert service.settings.primary_review_model == "env-primary-review"
    assert service.settings.secondary_review_model == "env-secondary-review"
    assert service.settings.embedding_model == "env-embedding"
