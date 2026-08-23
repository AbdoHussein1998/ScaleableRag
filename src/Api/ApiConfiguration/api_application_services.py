# api_application_services.py

from typing import Any, Optional, Protocol, runtime_checkable
import loguru
from Api.ApiConfiguration.api_settings import ApplicationBasicSettings

# All imports at top
from DatabaseInfrastructure.Mongodb import MongoConnectionManager
from DatabaseInfrastructure.PostgreSQL import PostgresConnectionManager
from DatabaseInfrastructure.Redis.async_connection import RedisConnectionManager
from qdrant_client import AsyncQdrantClient
from LLM.Embedding import EmbeddingFactory, EmbeddingConfig
from LLM.Generation import GenerationFactory, GenerationConfig


# ═══════════════════════════════════════════════════════════════
#  Protocol
# ═══════════════════════════════════════════════════════════════

@runtime_checkable
class ServiceManager(Protocol):
    async def connect(self, settings: ApplicationBasicSettings) -> None: ...
    async def disconnect(self) -> None: ...


# ═══════════════════════════════════════════════════════════════
#  MongoDB Manager
# ═══════════════════════════════════════════════════════════════



class MongoManager:
    def __init__(self, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger

        # Omni (primary) connection — reads + writes + everything
        self.omni_mongo_connection: Optional[Any] = None

        # Reserved for future split:
        # self.read_mongo_connection: Optional[Any] = None
        # self.write_mongo_connection: Optional[Any] = None
        # self.logs_mongo_connection: Optional[Any] = None

    async def connect(self, settings: ApplicationBasicSettings) -> None:
        self.logger.info("[MongoManager] connecting OMNI Mongo connection...")
        try:
            self.omni_mongo_connection = await MongoConnectionManager.init_class(
                mongo_url=settings.OMNI_MONGO_URL,db_name=settings.OMNI_MONGO_DB_NAME
            )
        except Exception as exc:
            self.logger.exception(f"[MongoManager] OMNI connection failed: {exc}")
            raise

    async def disconnect(self) -> None:
        if self.omni_mongo_connection is not None:
            try:
                self.logger.info("[MongoManager] disconnecting OMNI Mongo connection...")
                await self.omni_mongo_connection.disconnect()
            except Exception as exc:
                self.logger.error(f"[MongoManager] OMNI disconnect failed: {exc}")


# ═══════════════════════════════════════════════════════════════
#  PostgreSQL Manager
# ═══════════════════════════════════════════════════════════════

class PostgresManager:
    def __init__(self, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger

        # Omni (primary) connection/pool
        self.omni_postgres_conn: Optional[Any] = None


    async def connect(self, settings: ApplicationBasicSettings) -> None:
        self.logger.info("[PostgresManager] connecting OMNI PostgreSQL connection...")
        try:
            self.omni_postgres_conn = await PostgresConnectionManager.init_class(
                host=settings.OMNI_POSTGRES_HOST,
                port=settings.OMNI_POSTGRES_PORT,
                username=settings.OMNI_POSTGRES_USER,
                password=settings.OMNI_POSTGRES_PASSWORD,
                database=settings.OMNI_POSTGRES_DB,
                pool_size=settings.OMNI_POSTGRES_POOL_SIZE,
                max_overflow=settings.OMNI_POSTGRES_MAX_OVERFLOW,
                pool_timeout=settings.OMNI_POSTGRES_POOL_TIMEOUT,
                pool_recycle=settings.OMNI_POSTGRES_POOL_RECYCLE,
                echo=settings.OMNI_POSTGRES_ECHO,
                logger=self.logger,
            )
        except Exception as exc:
            self.logger.exception(f"[PostgresManager] OMNI connection failed: {exc}")
            raise

    async def disconnect(self) -> None:
        if self.omni_postgres_conn is not None:
            try:
                self.logger.info("[PostgresManager] disconnecting OMNI PostgreSQL connection...")
                await self.omni_postgres_conn.disconnect()
            except Exception as exc:
                self.logger.error(f"[PostgresManager] OMNI disconnect failed: {exc}")


# ═══════════════════════════════════════════════════════════════
#  Redis Manager
# ═══════════════════════════════════════════════════════════════
  


class RedisManager:

    def __init__(self, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger

        # Omni (primary) Redis connection
        self.omni_redis_conn: Optional[Any] = None


    async def connect(self, settings: ApplicationBasicSettings) -> None:
        self.logger.info("[RedisManager] connecting OMNI Redis...")
        try:
            self.omni_redis_conn = await RedisConnectionManager.init_class(
                redis_url=settings.OMNI_REDIS_URL,
            )
        except Exception as exc:
            self.logger.exception(f"[RedisManager] OMNI connection failed: {exc}")
            raise

    async def disconnect(self) -> None:
        if self.omni_redis_conn is not None:
            try:
                self.logger.info("[RedisManager] disconnecting OMNI Redis...")
                await self.omni_redis_conn.disconnect()
            except Exception as exc:
                self.logger.error(f"[RedisManager] OMNI disconnect failed: {exc}")


# ═══════════════════════════════════════════════════════════════
#  Qdrant Manager
# ═══════════════════════════════════════════════════════════════

class QdrantManager:
    def __init__(self, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger

        # Omni (primary) Qdrant client
        self.omni_qdrant_client: Optional[Any] = None

        # Reserved for future split:
        # self.embeddings_qdrant_client: Optional[Any] = None
        # self.memory_qdrant_client: Optional[Any] = None

    async def connect(self, settings: ApplicationBasicSettings) -> None:
        self.logger.info("[QdrantManager] connecting OMNI Qdrant...")
        try:
            self.omni_qdrant_client = AsyncQdrantClient(url=settings.OMNI_QDRANT_URL)
        except Exception as exc:
            self.logger.exception(f"[QdrantManager] OMNI connection failed: {exc}")
            raise

    async def disconnect(self) -> None:
        if self.omni_qdrant_client is not None:
            try:
                self.logger.info("[QdrantManager] disconnecting OMNI Qdrant...")
                await self.omni_qdrant_client.close()
            except Exception as exc:
                self.logger.error(f"[QdrantManager] OMNI disconnect failed: {exc}")


# ═══════════════════════════════════════════════════════════════
#  LLM Manager
# ═══════════════════════════════════════════════════════════════

    
class LLMManager:

    def __init__(self, logger: Optional[loguru._logger.Logger] = None):
        self.logger = logger or loguru.logger

        # Omni (primary) model handles
        self.omni_llm_gen: Optional[Any] = None
        self.omni_llm_embd: Optional[Any] = None

    async def connect(self, settings: ApplicationBasicSettings) -> None:
        self.logger.info("[LLMManager] loading OMNI GENERATION model...")
        try:
            gen_config = GenerationConfig(
                api_key=settings.OMNI_GENERATION_MODEL_API_KEY,
                base_url=settings.OMNI_GENERATION_MODEL_CONNECTION_URL,
                model_name=settings.OMNI_GENERATION_MODEL,
            )
            self.omni_llm_gen = await GenerationFactory.create_llm(
                model_config=gen_config,
                logger=self.logger,
            )
        except Exception as exc:
            self.logger.exception(f"[LLMManager] OMNI generation load failed: {exc}")
            raise

        self.logger.info("[LLMManager] loading OMNI EMBEDDING model...")
        try:
            emb_config = EmbeddingConfig(
                api_key=settings.OMNI_EMBEDDING_MODEL_API_KEY,
                base_url=settings.OMNI_EMBEDDING_MODEL_CONNECTION_URL,
                model_name=settings.OMNI_EMBEDDING_MODEL,
            )
            self.omni_llm_embd = await EmbeddingFactory.create_llm(
                model_config=emb_config,
                logger=self.logger,
            )
        except Exception as exc:
            self.logger.exception(f"[LLMManager] OMNI embedding load failed: {exc}")
            raise

    async def disconnect(self) -> None:
        self.logger.info("[LLMManager] shutting down OMNI models...")
        for name, model in (
            ("omni_generation", self.omni_llm_gen),
            ("omni_embedding", self.omni_llm_embd),
        ):
            if model is not None and hasattr(model, "close"):
                try:
                    await model.close()
                except Exception as exc:
                    self.logger.error(f"[LLMManager] {name} close failed: {exc}")


# ═══════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════

ALL_MANAGERS: dict[str, type] = {
    "mongo": MongoManager,
    "postgres": PostgresManager,
    "redis": RedisManager,
    "qdrant": QdrantManager,
    "llm": LLMManager,
}