_PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "label": "Groq",
        "default_model": "openai/gpt-oss-120b",
    },
    "openai": {
        "base_url": None,  # openai SDK 기본값 사용
        "label": "OpenAI",
        "default_model": "gpt-4o",
    },
    "anthropic": {
        "base_url": None,  # anthropic SDK 사용
        "label": "Anthropic",
        "default_model": "claude-sonnet-4-20250514",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "label": "Mistral AI",
        "default_model": "mistral-large-latest",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "label": "Google Gemini",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "label": "OpenRouter",
        "default_model": "google/gemini-2.5-flash",
    },
    "nvidia_nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "label": "NVIDIA NIM",
        "default_model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "label": "Ollama (로컬)",
        "default_model": "llama3.2",
        "requires_api_key": False,
    },
}

_KEY_MAP = {
    "groq": "groq_api_key", "openai": "openai_api_key", "anthropic": "anthropic_api_key",
    "mistral": "mistral_api_key", "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key", "nvidia_nim": "nvidia_nim_api_key",
    "ollama": "",
}

