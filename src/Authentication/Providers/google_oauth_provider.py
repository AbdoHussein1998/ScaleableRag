import os
import secrets
import loguru
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status
from authlib.integrations.starlette_client import OAuth


class GoogleOAuthHandler:
    def __init__(self, logger: Optional[loguru.Logger] = None) -> None:
        self.logger = logger or loguru.logger
        self.oauth = OAuth()

        self.oauth.register(
            name="google",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile",
                "prompt": "select_account",  # lets users pick/change accounts
            },
        )

    @classmethod
    async def init_class(cls, logger: Optional[loguru.Logger] = None) -> "GoogleOAuthHandler":
        logger = logger or loguru.logger
        logger.info("Initializing Google OAuth provider...")
        try:
            return cls(logger)
        except Exception as e:
            logger.error(f"Failed to initialize Google OAuth provider: {e}")
            raise

    # ─── Redirect ───

    async def redirect_to_google(self, request: Request) -> Any:
        redirect_uri = self._get_redirect_uri(request)
        self.logger.info(f"OAuth redirect URI: {redirect_uri}")

        # CSRF protection: generate random state and stash in session
        state = secrets.token_urlsafe(32)      
        # Generate a random state value

        request.session["oauth_state"] = state
        # Store the generated state in the user's session
        # so we can verify it later when Google redirects back

        return await self.oauth.google.authorize_redirect(
            request,
            # Pass the current request to the OAuth library

            redirect_uri,
            state=state,
            # Send the generated state to Google
        )

    # ─── Callback ───

    async def receiving_from_google(self, request: Request) -> Dict[str, Any]:
        # 1. Verify state to prevent CSRF
        state_param = request.query_params.get("state")
        state_session = request.session.get("oauth_state")

        if not state_param or not state_session or state_param != state_session:
            self.logger.warning("OAuth state mismatch — possible CSRF attack")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid OAuth state"
            )

        # One-time use: burn the state immediately
        request.session.pop("oauth_state", None)

        # 2. Exchange code for token (handle user-denied, bad code, network errors)
        try:
            token = await self.oauth.google.authorize_access_token(request)
        except Exception as e:
            self.logger.error(f"Google token exchange failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google authentication failed or was denied"
            )

        # 3. Extract and validate userinfo
        user = token.get("userinfo")

        if not user:
            self.logger.error("No userinfo in Google token response")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to retrieve user information from Google"
            )

        if not user.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Google account: missing subject identifier"
            )

        if not user.get("email"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account email is required"
            )

        # Optional but recommended: enforce verified emails only
        if not user.get("email_verified"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google email must be verified"
            )

        return user

    # ─── Helpers ───

    def _get_redirect_uri(self, request: Request) -> str:
        """
        Build the redirect URI, respecting X-Forwarded-Proto when behind
        a reverse proxy (Nginx, Traefik, etc.).
        """
        url = request.url_for("google_callback")

        # If a reverse proxy terminated TLS, it usually sets this header
        forwarded_proto = request.headers.get("x-forwarded-proto")
        if forwarded_proto:
            # Reconstruct: https://host/path
            return f"{forwarded_proto}://{url.netloc}{url.path}"

        return str(url)


