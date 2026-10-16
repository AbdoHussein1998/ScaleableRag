from pydantic import BaseModel
from typing import Optional
from datetime import datetime



from typing import Optional, Any
from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """JWT payload model. Used for both encoding (issuing) and decoding (verifying)."""

    # ─── Application Claims ───
    sub: str = Field(description="Subject identifier, e.g. google_sub or user_id")
    email: Optional[str] = Field(default=None, description="User email address")
    name: Optional[str] = Field(default=None, description="Display name")
    picture_url: Optional[str] = Field(default=None, description="Avatar / profile picture URL")

    # ─── Standard JWT Claims (populated on decode, excluded on encode) ───
    jti: Optional[str] = Field(default=None, description="JWT unique identifier")
    type: Optional[str] = Field(default=None, description="Token type: access | refresh")
    family: Optional[str] = Field(default=None, description="Refresh token family UUID")
    iat: Optional[int] = Field(default=None, description="Issued at (Unix timestamp)")
    exp: Optional[int] = Field(default=None, description="Expiration time (Unix timestamp)")

    # Allow any extra claims (iss, aud, etc.) to pass through without validation errors
    model_config = {"extra": "allow"}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TokenPayload":
        """Reconstruct from a decoded JWT dictionary (e.g. jwt.decode output)."""
        return cls(
            sub=payload.get("sub"),
            email=payload.get("email"),
            name=payload.get("name"),
            picture_url=payload.get("picture_url"),
            jti=payload.get("jti"),
            type=payload.get("type"),
            family=payload.get("family"),
            iat=payload.get("iat"),
            exp=payload.get("exp"),
            **{k: v for k, v in payload.items() if k not in {
                "sub", "email", "name", "picture_url",
                "jti", "type", "family", "iat", "exp"
            }},
        )