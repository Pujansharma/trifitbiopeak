from hashlib import sha256
from secrets import token_hex


def generate_service_account_token() -> str:
    return token_hex(16)


def hash_service_account_token(token: str) -> str:
    return sha256(token.lower().encode("utf-8")).hexdigest()
