import os


# 자식 프로세스에 전달하지 않을 환경 변수 접두사 (API 키 등 민감 정보)
_SENSITIVE_ENV_PREFIXES = (
    "OPENAI_", "GROQ_", "ANTHROPIC_", "SUPABASE_",
    "GEMINI_", "MISTRAL_", "COHERE_", "DEEPSEEK_",
    "AWS_", "AZURE_", "GCP_", "GOOGLE_",
    "GITHUB_", "GITLAB_", "DISCORD_", "SLACK_",
    "DATABASE_", "DB_", "MONGO_", "REDIS_", "POSTGRES_",
    "API_KEY", "SECRET_", "TOKEN_", "PASSWORD_", "PRIVATE_",
)
_SENSITIVE_ENV_SUBSTRINGS = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE")


def _is_sensitive_env_var(name: str) -> bool:
    normalized = (name or "").upper()
    return any(normalized.startswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES) or any(
        token in normalized for token in _SENSITIVE_ENV_SUBSTRINGS
    )


def _build_child_env() -> dict:
    """민감한 환경변수를 제외한 안전한 자식 프로세스 환경 반환."""
    return {
        k: v for k, v in os.environ.items()
        if not _is_sensitive_env_var(k)
    }


