# fast_api_config.py
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
import loguru

from .api_settings import get_basic_settings, ApplicationBasicSettings
from .api_application_services import (
    MongoManager,
    PostgresManager,
    RedisManager,
    QdrantManager,
    LLMManager,
)


class ApplicationServices:
    """Minimalist container: owns every manager. No logic, just wiring."""

    def __init__(self, settings: ApplicationBasicSettings, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger
        self.settings = settings

        # Instantiate managers (no I/O yet)
        self.mongo = MongoManager(logger=self.logger)
        self.postgres = PostgresManager(logger=self.logger)
        self.redis = RedisManager(logger=self.logger)
        self.qdrant = QdrantManager(logger=self.logger)
        self.llm = LLMManager(logger=self.logger)

    async def startup(self) -> None:
        """Connect everything in dependency order."""
        await self.mongo.connect(self.settings)
        await self.redis.connect(self.settings)
        await self.postgres.connect(self.settings)
        # await self.qdrant.connect(self.settings)
        # await self.llm.connect(self.settings)

    async def shutdown(self) -> None:
        """Disconnect everything (reverse order, errors swallowed per-manager)."""
        await self.mongo.disconnect()
        await self.redis.disconnect()
        await self.postgres.disconnect()
        await self.llm.disconnect()
        await self.qdrant.disconnect()


def create_lifespan(logger: Optional[loguru._logger.Logger] = None):
    if logger is None:
        logger = loguru.logger

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("API Backend is starting up...")

        # 1. Settings
        app.state.basic_settings = get_basic_settings()

        # 2. Create & start all services
        app.state.services = ApplicationServices(
            settings=app.state.basic_settings,
            logger=logger,
        )
        await app.state.services.startup()

        yield

        # 3. Graceful shutdown
        logger.info("API Backend is shutting down...")
        await app.state.services.shutdown()

    return lifespan


