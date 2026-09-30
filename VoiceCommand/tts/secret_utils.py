def redact_secret(value: str, secret: str) -> str:
    return value.replace(secret, "[redacted]") if secret else value
