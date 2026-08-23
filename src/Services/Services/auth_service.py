import os
import loguru
from typing import Optional
from fastapi import Request
from fastapi.responses import FileResponse, Response

from Services.service_interface import ServiceInterface
from Authentication.Providers.google_oauth_provider import GoogleOAuthHandler
from Authentication.Providers.jwt_services_provider import JWTHandler
from DatabaseInfrastructure.PostgreSQL.async_dml import PostgresDML
from DatabaseInfrastructure.PostgreSQL.async_connection import PostgresConnectionManager
from Authentication.Schema.models import TokenPayload
from pprint import pprint as pp

class AuthService(ServiceInterface):
    def __init__(
        self,
        post_connection_manager: PostgresConnectionManager,
        logger: Optional[loguru.Logger] = None,
    ) -> None:
        self.google_auth_handler: Optional[GoogleOAuthHandler] = None
        self.jwt_handler: Optional[JWTHandler] = None
        self.postgres: Optional[PostgresDML] = None
        self.post_connection_manager: PostgresConnectionManager = post_connection_manager
        self.logger: loguru.Logger = logger or loguru.logger

        # Store the PATH only — never a shared Response object
        self.welcome_page_path = os.getenv(
            "WELCOME_PAGE_PATH",
            r"E:\SPgroup\Technical\Current\Ai Analysis Qualuity System\Frontend\welcome.html",
        )

    @classmethod
    async def init_service(
        cls,
        post_connection_manager: PostgresConnectionManager,
        logger: Optional[loguru.Logger] = None,
    ) -> "AuthService":
        logger = logger or loguru.logger
        instance = cls(post_connection_manager, logger=logger)
        instance.google_auth_handler = await GoogleOAuthHandler.init_class(logger=logger)
        instance.jwt_handler = await JWTHandler.init_class(logger=logger)
        instance.postgres = await PostgresDML.init_class(manager=post_connection_manager)
        return instance

    # ─── OAuth passthrough ───

    async def redirect_to_google(self, request: Request):
        # GoogleOAuthHandler now generates state and stores it in session
        return await self.google_auth_handler.redirect_to_google(request)

    async def receiving_from_google(self, request: Request):
        # Now validates state, userinfo, and email_verified internally.
        # Raises HTTPException on any error — no need to check for None here.
        return await self.google_auth_handler.receiving_from_google(request)

    # ─── Database ───
    async def save_to_database(self, data: dict) -> None:
        self.logger.info(f"Processing user data for database: {data}")

        db_data = {
            "google_sub": data.get("sub"),
            "email": data.get("email"),
            "email_verified": data.get("email_verified", False),
            "name": data.get("name"),
            "given_name": data.get("given_name"),
            "family_name": data.get("family_name"),
            "picture_url": data.get("picture"),
        }

        if not db_data["google_sub"] or not db_data["email"]:
            raise ValueError("Missing required fields: 'sub' and 'email' are required")

        # Defense in depth: GoogleOAuthHandler already enforces this,
        # but we keep it in case this method is called from elsewhere.
        if not db_data["email_verified"]:
            raise ValueError("Email must be verified before saving")

        self.logger.info(f"Upserting user data: {db_data}")


        await self.postgres.insert_into_table(
            table_name="users",
            data=db_data,
            schema="auth",
        )



    # ─── Tokens ───

    async def generate_tokens(self, data: dict) -> dict:
        google_sub = data.get("google_sub") or data.get("sub")
        email = data.get("email")
        if not google_sub or not email:
            raise ValueError("Missing required fields: sub and email")
        pp(data)
        payload = TokenPayload(
            sub=google_sub,
            name=data.get("name") or data.get("given_name"),
        )
        pp(payload)
        access_token = await self.jwt_handler.generate_access_token(payload)
        refresh_token = await self.jwt_handler.generate_refresh_token(payload)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.jwt_handler.access_token_expire_minutes * 60,
        }

    # ─── Response / Cookies ───

    async def go_to_home_and_store_token(self, token_data: dict) -> Response:
        """
        Create a fresh FileResponse for EVERY request.
        NEVER reuse a Response object across requests — that leaks cookies.
        """
        response = FileResponse(self.welcome_page_path)

        self.jwt_handler.set_auth_cookies(
            response=response,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
        )
        return response