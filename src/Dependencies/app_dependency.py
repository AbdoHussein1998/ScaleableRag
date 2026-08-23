# src\Dependencies\app_dependency.py


from fastapi import Depends, Request
import loguru

from Api.ApiConfiguration.fast_api_config import ApplicationServices


def get_app_services(request: Request) -> ApplicationServices:
    """Extracts the central services container from application state."""
    return request.app.state.services