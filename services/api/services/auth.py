"""
Authentication Service for API.
Handles JWT token creation, verification, and refresh token rotation.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext

MSK = timezone(timedelta(hours=3))


class AuthService:
    """JWT-based authentication service with refresh token rotation."""

    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    pwd_context: CryptContext

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 15,
        refresh_token_expire_days: int = 7,
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # =========================================================================
    # Password helpers
    # =========================================================================

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return self.pwd_context.verify(plain_password, hashed_password)

    def hash_password(self, password: str) -> str:
        """Hash a password."""
        return self.pwd_context.hash(password)

    # =========================================================================
    # Access token
    # =========================================================================

    def create_access_token(
        self,
        user_id: int,
        username: str,
        role: str,
        sid: int,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a JWT access token."""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)

        expire = datetime.now(MSK) + expires_delta

        to_encode = {
            "sub": str(user_id),
            "user_id": user_id,
            "username": username,
            "role": role,
            "sid": sid,
            "exp": expire,
            "type": "access",
        }

        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT token. Raises JWTError on failure."""
        payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        return payload

    def verify_access_token(self, token: str) -> Optional[dict]:
        """Verify an access token and return payload or None."""
        try:
            payload = self.verify_token(token)
            if payload.get("type") != "access":
                return None
            return payload
        except JWTError:
            return None

    # =========================================================================
    # Refresh token (opaque)
    # =========================================================================

    @staticmethod
    def generate_refresh_token() -> str:
        """Generate a cryptographically secure opaque refresh token."""
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash a token using SHA-256 for secure DB storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_refresh_token(self, user_id: int) -> Tuple[str, str, datetime]:
        """
        Create a refresh token.

        Returns:
            (raw_token, token_hash, expires_at)
            - raw_token: sent to client as HttpOnly cookie
            - token_hash: stored in DB (never store raw)
            - expires_at: expiration timestamp
        """
        raw_token = self.generate_refresh_token()
        token_hash = self.hash_token(raw_token)
        expires_at = datetime.now(MSK) + timedelta(
            days=self.refresh_token_expire_days
        )
        return raw_token, token_hash, expires_at

    @staticmethod
    def generate_family_id() -> str:
        """Generate a unique family ID for a token rotation chain."""
        return secrets.token_urlsafe(16)
