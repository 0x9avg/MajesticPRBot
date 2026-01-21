"""
Authentication Service for API.
Handles JWT token creation and verification.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import secrets
import hashlib

from jose import jwt, JWTError
from passlib.context import CryptContext


class AuthService:
    """JWT-based authentication service."""
    
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
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def hash_password(self, password: str) -> str:
        """Hash a password."""
        return self.pwd_context.hash(password)
    
    def create_access_token(
        self,
        user_id: int,
        username: str,
        role: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a JWT access token."""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)
        
        expire = datetime.now(timezone.utc) + expires_delta
        
        to_encode = {
            "sub": str(user_id),
            "user_id": user_id,
            "username": username,
            "role": role,
            "exp": expire,
            "type": "access",
        }
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(self, user_id: int) -> Tuple[str, datetime]:
        """Create a refresh token. Returns (token, expires_at)."""
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)
        
        # Generate a secure random token
        random_bytes = secrets.token_bytes(32)
        token_hash = hashlib.sha256(
            f"{user_id}:{random_bytes.hex()}:{expires_at.isoformat()}".encode()
        ).hexdigest()
        
        return token_hash, expires_at
    
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
