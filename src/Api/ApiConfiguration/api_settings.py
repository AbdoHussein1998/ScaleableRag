#api_settings.py


from pydantic_settings import BaseSettings,SettingsConfigDict



from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationBasicSettings(BaseSettings):
    """
    Basic settings for the application.
    All primary/omni connections use the OMNI_ prefix.
    Future read/write/cache splits will use their own prefixes.
    """

    #########################
    # Application
    #########################
    APP_NAME: str
    APP_VERSION: str

    #########################
    # MongoDB — OMNI (primary)
    #########################
    OMNI_MONGO_URL: str
    OMNI_MONGO_DB_NAME: str  # App-level (not connection-specific)

    #########################
    # PostgreSQL — OMNI (primary)
    #########################
    OMNI_POSTGRES_HOST: str 
    OMNI_POSTGRES_PORT: int 
    OMNI_POSTGRES_USER: str
    OMNI_POSTGRES_PASSWORD: str
    OMNI_POSTGRES_DB: str
    OMNI_POSTGRES_POOL_SIZE: int 
    OMNI_POSTGRES_MAX_OVERFLOW: int 
    OMNI_POSTGRES_POOL_TIMEOUT: int 
    OMNI_POSTGRES_POOL_RECYCLE: int 
    OMNI_POSTGRES_ECHO: bool = False


    #########################
    # Redis — OMNI (primary)
    #########################
    OMNI_REDIS_URL: str

    #########################
    # Qdrant — OMNI (primary)
    #########################
    # OMNI_QDRANT_URL: str



    #########################
    # Embedding — OMNI (primary)
    #########################
    # OMNI_EMBEDDING_MODEL: str
    # OMNI_EMBEDDING_MODEL_API_KEY: str
    # OMNI_EMBEDDING_PROVIDER: str
    # OMNI_EMBEDDING_MODEL_CONNECTION_URL: str
    # Future:
    # CHEAP_EMBEDDING_MODEL: str
    # FAST_EMBEDDING_MODEL: str

    #########################
    # Generation — OMNI (primary)
    #########################
    # OMNI_GENERATION_MODEL: str
    # OMNI_GENERATION_MODEL_CONNECTION_URL: str
    # OMNI_GENERATION_MODEL_API_KEY: str



    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    CELERY_BROKER_CONNECTUIONS_POOL:int



    JWT_SECRET_KEY:str
    JWT_HASHING_ALGORITHM:str
    GOOGLE_CLIENT_ID:str
    GOOGLE_CLIENT_SECRET:str





    model_config = SettingsConfigDict(
        env_file="src/.env",
        extra="ignore",
    )



def get_basic_settings() -> ApplicationBasicSettings:
    """
    Get the basic settings for the application.
    """
    return ApplicationBasicSettings()







