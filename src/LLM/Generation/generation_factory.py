from dataclasses import dataclass, asdict, field
from typing import Optional, Final, Dict, Any
from langchain.chat_models import init_chat_model
import loguru
import asyncio


# =========================================================
# 1. Config Dataclass
# =========================================================

@dataclass
class GenerationConfig:
    """Holds all LLM configuration including credentials."""

    model_name: str = "llama3"
    model_provider: str = "ollama"
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    max_retries: int = 2
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    def __post_init__(self):
        """Sanitize and validate inputs."""
        if not isinstance(self.model_name, str):
            raise TypeError(f"model_name must be a string, got {type(self.model_name)}")
        if not isinstance(self.model_provider, str):
            raise TypeError(
                f"model_provider must be a string, got {type(self.model_provider)}"
            )

        self.model_name = self.model_name.strip().lower()
        self.model_provider = self.model_provider.strip().lower()

        if not self.model_name:
            raise ValueError("model_name cannot be empty")
        if not self.model_provider:
            raise ValueError("model_provider cannot be empty")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for langchain, mapping model_name -> model."""
        result = {}
        for k, v in asdict(self).items():
            if v is None:
                continue
            # langchain expects 'model', not 'model_name'
            key = "model" if k == "model_name" else k
            result[key] = v
        return result


# =========================================================
# 2. Generation Factory
# =========================================================

class GenerationFactory:
    """Factory class for creating LLM instances."""

    SUPPORTED_PROVIDERS: Final[frozenset[str]] = frozenset({
        "openai",
        "azure_openai",
        "anthropic",
        "google_vertexai",
        "google_genai",
        "bedrock",
        "cohere",
        "fireworks",
        "together",
        "mistralai",
        "huggingface",
        "groq",
        "ollama",
    })

    @classmethod
    def _validate_config(
        cls,
        model_config: GenerationConfig,
        logger: loguru._logger.Logger,
    ) -> None:
        """Validate GenerationConfig instance."""

        if not isinstance(model_config, GenerationConfig):
            raise TypeError(
                f"model_config must be a GenerationConfig instance, got {type(model_config)}"
            )

        if model_config.model_provider not in cls.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider: '{model_config.model_provider}'. "
                f"Supported providers: {', '.join(sorted(cls.SUPPORTED_PROVIDERS))}"
            )

        logger.debug(
            "Config validated | provider='{}', model_name='{}'",
            model_config.model_provider,
            model_config.model_name,
        )

    @classmethod
    async def create_llm(
        cls,
        model_config: Optional[GenerationConfig] = None,
        logger: Optional[loguru._logger.Logger] = None,
    ):
        """Create an LLM instance from a single config object."""

        logger = logger or loguru.logger
        model_config = model_config or GenerationConfig()

        logger.info(
            "Creating LLM | provider='{}', model_name='{}'",
            model_config.model_provider,
            model_config.model_name,
        )

        # --- Validate ---
        try:
            cls._validate_config(model_config, logger)
        except (TypeError, ValueError) as e:
            logger.error("Validation failed: {}", str(e))
            raise

        # --- Build kwargs ---
        kwargs = model_config.to_dict()

        # --- Create model ---
        try:
            llm = await asyncio.wait_for(
                asyncio.to_thread(init_chat_model, **kwargs),
                timeout=120
            )
            logger.success(
                "LLM created successfully | provider='{}', model_name='{}'",
                model_config.model_provider,
                model_config.model_name,
            )
            return llm

        except ImportError as e:
            logger.error(
                "Missing provider package for '{}': {}",
                model_config.model_provider,
                str(e),
            )
            raise
        except Exception as e:
            logger.error("Failed to create LLM: {}", str(e))
            raise


        