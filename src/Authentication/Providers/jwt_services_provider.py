import os
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import Request, Response, HTTPException, status
import loguru

from Authentication.Schema.models import TokenPayload
from pprint import pprint as pp

class JWTHandler:
    def __init__(self, logger: Optional[loguru.Logger] = None) -> None:
        self.secret_key = os.getenv("JWT_SECRET_KEY")
        if not self.secret_key:
            raise RuntimeError("JWT_SECRET_KEY environment variable is required")

        self.hash_algorithm = os.getenv("JWT_HASHING_ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "5")
        )
        self.refresh_token_expire_days = int(
            os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7")
        )
        self.issuer = os.getenv("APP_NAME")
        self.audience = "SIGNING_IN"
        self.cookie_secure = os.getenv("COOKIE_SECURE", "true").lower() == "true"
        self.logger = logger or loguru.logger

    @classmethod
    async def init_class(cls, logger: Optional[loguru.Logger] = None) -> "JWTHandler":
        return cls(logger)

    # ─── Core Payload Builder ───


    def _create_payload(
        self,
        data: Dict[str, Any],
        expires_delta: timedelta,
        token_type: str,
        jti: Optional[str] = None,
        family: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a standard JWT payload with security claims."""
        now = datetime.now(timezone.utc)
        jti = jti or str(uuid.uuid4())

        payload = {
            **data,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
            "jti": jti,
            "type": token_type,
            "iss": self.issuer,
            "aud": self.audience,
        }
        if family:
            payload["family"] = family

        return payload

    # ─── Token Generation ───

    async def generate_access_token(
        self,
        data: TokenPayload,
        family: Optional[str] = None,
    ) -> str:
        """Generate a short-lived access token."""

        payload = self._create_payload(
            data.model_dump(exclude={"exp", "iat", "type", "jti"}), # to Transform the TokenPayload into dict
            timedelta(minutes=self.access_token_expire_minutes),
            token_type="access",
            family=family,
        )
   
        self.logger.debug(f"Access token issued | sub={data.sub} jti={payload['jti']}")
        return jwt.encode(payload, self.secret_key, algorithm=self.hash_algorithm)



    async def generate_refresh_token(
        self,
        data: TokenPayload,
        family: Optional[str] = None,
    ) -> tuple[str, str, str]:
        """
        Generate a long-lived refresh token.
        Returns: (token_string, jti, family)
        """
        family = family or str(uuid.uuid4())
        payload = self._create_payload(
            {"sub": data.sub, "name": getattr(data, "name", None)},
            timedelta(days=self.refresh_token_expire_days),
            token_type="refresh",
            family=family,
        )
        token = jwt.encode(payload, self.secret_key, algorithm=self.hash_algorithm)

        self.logger.debug(
            f"Refresh token issued | sub={data.sub} jti={payload['jti']} family={family}"
        )
        return token, payload["jti"], family

    # ─── Verification ───

    async def verify_token(
        self,
        token: str,
        expected_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify signature, expiry, issuer, audience. Optionally enforce token type."""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.hash_algorithm],
                issuer=self.issuer,
                audience=self.audience,
            )
        except jwt.ExpiredSignatureError:
            self.logger.warning("Token verification failed: expired signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            self.logger.warning(f"Token verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if expected_type and payload.get("type") != expected_type:
            self.logger.warning(
                f"Token type mismatch | expected={expected_type} got={payload.get('type')}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token type: expected {expected_type}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    async def verify_access_token(self, token: str) -> Dict[str, Any]:
        """Convenience wrapper that enforces type='access'."""
        return await self.verify_token(token, expected_type="access")

    async def verify_refresh_token(self, token: str) -> Dict[str, Any]:
        """Convenience wrapper that enforces type='refresh'."""
        return await self.verify_token(token, expected_type="refresh")

    # ─── Refresh Flow (Token Rotation) ───

    async def rotate_tokens(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh token rotation:
        1. Verify the incoming refresh token
        2. Reconstruct the user payload
        3. Issue a NEW access token + NEW refresh token (same family)
        
        Returns metadata so AuthService can revoke the old jti in DB.
        """
        payload = await self.verify_refresh_token(refresh_token)

        # Reconstruct Pydantic payload for the generators
        token_payload = TokenPayload(
            sub=payload["sub"],
            name=payload.get("name"),
        )
        family = payload.get("family")
        old_jti = payload.get("jti")

        access_token = await self.generate_access_token(token_payload, family=family)
        new_refresh_token, new_jti, _ = await self.generate_refresh_token(
            token_payload, family=family
        )

        self.logger.info(
            f"Token rotated | sub={payload['sub']} old_jti={old_jti} new_jti={new_jti}"
        )

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": self.access_token_expire_minutes * 60,
            "family": family,
            "old_jti": old_jti,      # ← AuthService should revoke this in DB
            "new_jti": new_jti,      # ← AuthService should store this in DB
        }

    # ─── Cookie Helpers ───

    def set_auth_cookies(
        self,
        response: Response,
        access_token: str,
        refresh_token: str,
    ) -> None:
        """Store tokens in HTTP-only cookies."""
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=self.cookie_secure,
            samesite="lax",
            max_age=self.access_token_expire_minutes * 60,
            path="/",
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=self.cookie_secure,
            samesite="lax",
            max_age=self.refresh_token_expire_days * 86400,
            path="/auth/refresh",
        )
        self.logger.debug("Auth cookies set on response")

    def clear_auth_cookies(self, response: Response) -> None:
        """Clear cookies on logout."""
        response.delete_cookie("access_token", path="/")
        response.delete_cookie("refresh_token", path="/auth/refresh")
        self.logger.debug("Auth cookies cleared")

    # ─── Request Extractors ───

    async def get_access_token_from_request(self, request: Request) -> str:
        """Extract access token from cookie or Authorization header."""
        if token := request.cookies.get("access_token"):
            return token

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def get_refresh_token_from_request(self, request: Request) -> str:
        """Extract refresh token from its dedicated cookie."""
        if token := request.cookies.get("refresh_token"):
            return token

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )