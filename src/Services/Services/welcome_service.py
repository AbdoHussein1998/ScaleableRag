#welcome_service.py


import loguru
from typing import Optional
from Services.service_interface import ServiceInterface

from typing import Optional
import loguru


class WelcomeService(ServiceInterface):
    def __init__(self, logger: Optional[loguru._logger.Logger] = None) -> None:
        self.logger = logger or loguru.logger

    @classmethod
    async def init_service(cls, logger: Optional[loguru._logger.Logger] = None):
        logger = logger or loguru.logger

        logger.info("Initializing Welcome service...")
        instance = cls(logger=logger)
        logger.success("Welcome service initialized successfully")

        return instance

    async def run(self) -> str:
        self.logger.info("Welcome service is running")
        return "Welcome to the Base RAG application"




