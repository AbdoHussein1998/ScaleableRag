import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Final, Optional

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
import loguru


# =========================================================
# 1. Config Dataclass
# =========================================================

@dataclass
class EmbeddingConfig:
    """Holds all embedding configuration including credentials."""

    embedding_provider: str = "ollama"
    model_name: str = "nomic-embed-text"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    extra_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Sanitize and validate inputs."""
        if not isinstance(self.embedding_provider, str):
            raise TypeError(
                f"embedding_provider must be a string, got {type(self.embedding_provider)}"
            )
        if not isinstance(self.model_name, str):
            raise TypeError(f"model_name must be a string, got {type(self.model_name)}")

        self.embedding_provider = self.embedding_provider.strip().lower()
        self.model_name = self.model_name.strip().lower()

        if not self.embedding_provider:
            raise ValueError("embedding_provider cannot be empty")
        if not self.model_name:
            raise ValueError("model_name cannot be empty")

    @property
    def model_str(self) -> str:
        """Build the 'provider:model' identifier expected by init_embeddings."""
        return f"{self.embedding_provider}:{self.model_name}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to kwargs dict for langchain's init_embeddings, folding in credentials."""
        result: Dict[str, Any] = dict(self.extra_kwargs)
        if self.api_key:
            result["api_key"] = self.api_key
        if self.base_url:
            result["base_url"] = self.base_url
        return result


# =========================================================
# 2. Embedding Factory
# =========================================================
class EmbeddingFactory:
    """Factory class for creating embedding instances from various providers."""

    SUPPORTED_PROVIDERS: Final[frozenset[str]] = frozenset({
        "openai",
        "azure_openai",
        "bedrock",
        "cohere",
        "google_vertexai",
        "huggingface",
        "mistralai",
        "ollama",
    })

    @classmethod
    def _validate_config(
        cls,
        embedding_config: EmbeddingConfig,
        logger: loguru._logger.Logger,
    ) -> None:
        """Validate EmbeddingConfig instance."""

        if not isinstance(embedding_config, EmbeddingConfig):
            raise TypeError(
                f"embedding_config must be an EmbeddingConfig instance, got {type(embedding_config)}"
            )

        if embedding_config.embedding_provider not in cls.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider: '{embedding_config.embedding_provider}'. "
                f"Supported providers: {', '.join(sorted(cls.SUPPORTED_PROVIDERS))}"
            )

        logger.debug(
            "Config validated | provider='{}', model_name='{}'",
            embedding_config.embedding_provider,
            embedding_config.model_name,
        )

    @classmethod

    async def create_llm(
        cls,
        embedding_config: Optional[EmbeddingConfig] = None,
        logger: Optional[loguru._logger.Logger] = None,
    ) -> Embeddings:
        """Create an embeddings instance from a single config object.

        Args:
            embedding_config: EmbeddingConfig instance. Falls back to defaults if not provided.
            logger: Optional loguru Logger instance. Falls back to default loguru logger.

        Returns:
            An Embeddings instance.

        Raises:
            TypeError: If embedding_config is not an EmbeddingConfig instance.
            ValueError: If provider is unsupported or inputs are empty.
        """

        logger = logger or loguru.logger
        embedding_config = embedding_config or EmbeddingConfig()

        logger.info(
            "Creating embeddings | provider='{}', model_name='{}'",
            embedding_config.embedding_provider,
            embedding_config.model_name,
        )

        # --- Validate ---
        try:
            cls._validate_config(embedding_config, logger)
        except (TypeError, ValueError) as e:
            logger.error("Validation failed: {}", str(e))
            raise

        # --- Build kwargs ---
        model_str = embedding_config.model_str
        kwargs = embedding_config.to_dict()

        if embedding_config.api_key:
            logger.debug("API key provided")
        if embedding_config.base_url:
            logger.debug("Custom base URL provided: '{}'", embedding_config.base_url)

        # --- Create embeddings ---
        try:
            embeddings = await asyncio.wait_for(
                asyncio.to_thread(init_embeddings, model_str, **kwargs),
                timeout=120,
            )
            logger.success("Embeddings created successfully | model_str='{}'", model_str)
            return embeddings

        except ImportError as e:
            logger.error(
                "Missing provider package for '{}': {}",
                embedding_config.embedding_provider,
                str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to create embeddings | model_str='{}': {}",
                model_str,
                str(e),
            )
            raise




