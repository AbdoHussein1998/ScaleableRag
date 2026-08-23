# src/Dependencies/google_auth_dependency.py

import loguru
from Services.Services.auth_service import AuthService
from fastapi import Request 
from Api.ApiConfiguration.fast_api_config import ApplicationServices
from .app_dependency import get_app_services


async def get_auth_service(request:Request) -> AuthService:

    app_services=get_app_services(request=request)
    post_con=app_services.postgres.omni_postgres_conn
    return await AuthService.init_service(
        post_connection_manager=post_con,
    )




