import hashlib
import hmac
import secrets

# Format: "scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>".
# Legacy format (still verified, rehashed on login): "<salt_hex>:<sha256_hex>".
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=dklen)


def _parse_scrypt(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    salt, expected = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    if not salt or not expected:
        return None
    return n, r, p, salt, expected


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash. Never raises."""
    try:
        if stored.startswith("scrypt$"):
            parsed = _parse_scrypt(stored)
            if parsed is None:
                return False
            n, r, p, salt, expected = parsed
            actual = _scrypt(password, salt, n, r, p, len(expected))
            return hmac.compare_digest(actual, expected)

        parts = stored.split(":")
        if len(parts) != 2:
            return False
        salt_hex, expected_hex = parts
        actual_hex = hashlib.sha256(f"{salt_hex}{password}".encode()).hexdigest()
        return hmac.compare_digest(actual_hex.encode(), expected_hex.encode())
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True when the stored hash is legacy, unknown or uses outdated parameters."""
    try:
        parsed = _parse_scrypt(stored)
    except Exception:
        return True
    if parsed is None:
        return True
    n, r, p, _, expected = parsed
    return (n, r, p, len(expected)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
