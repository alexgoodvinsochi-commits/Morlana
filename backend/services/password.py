import hashlib
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{pwd_hash}"


def verify_password(password: str, stored: str) -> bool:
    salt, pwd_hash = stored.split(":")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == pwd_hash
