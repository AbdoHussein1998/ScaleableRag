import asyncio
import time
from typing import Any, Callable, Optional
from functools import wraps
from DatabaseInfrastructure.Interfaces.connection import ConnectionManagerInterface
import redis.asyncio as redis
import loguru
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from functools import wraps


# Retryable errors for the @retry decorator
RETRYABLE_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    OSError,
)


class RedisConnectionManager(ConnectionManagerInterface):
    """
    Production-grade async Redis connection manager using redis-py async.

    Handles connection lifecycle, pooling, health checks, and reconnection.
    Used by DDL and DML classes via composition.

    Attributes:
        redis_url (str): Redis connection URL.
        client (Optional[redis.Redis]): Async Redis client.
        logger: Logger instance (loguru by default).
    """

    def __init__(
        self,
        redis_url: str,
        logger: Optional[Any] = None,
        max_pool_size: int = 20,
        connect_timeout_ms: int = 10000,
        socket_timeout_ms: int = 30000,
        health_check_interval: int = 30,
    ) -> None:
        """
        Initialize async Redis connection manager.

        Args:
            redis_url (str): Redis connection URL.
            logger: Optional custom logger (defaults to loguru).
            max_pool_size (int): Max concurrent connections. Default 20.
            connect_timeout_ms (int): TCP connect timeout. Default 10000.
            socket_timeout_ms (int): Per-operation socket timeout. Default 30000.
            health_check_interval (int): Seconds between active pings. Default 30.

        Raises:
            ValueError: If redis_url is not provided.
        """
        if not redis_url:
            raise ValueError("Connection_String not provided. Pass as argument")

        self.redis_url: str = redis_url
        self.max_pool_size = max_pool_size
        self.connect_timeout_ms = connect_timeout_ms
        self.socket_timeout_ms = socket_timeout_ms
        self.health_check_interval = health_check_interval

        self.client: Optional[redis.Redis] = None
        self.logger = logger if logger is not None else loguru.logger

        # For throttled health checks
        self._last_health_check: float = 0.0

        self.logger.info(
            f"RedisConnectionManager initialized | "
            f"pool max={self.max_pool_size} | "
            f"connect_timeout={self.connect_timeout_ms}ms | "
            f"socket_timeout={self.socket_timeout_ms}ms"
        )

    @classmethod
    async def init_class(
        cls,
        redis_url: str,
        logger: Optional[Any] = None,
        max_pool_size: int = 20,
        connect_timeout_ms: int = 10000,
        socket_timeout_ms: int = 30000,
        health_check_interval: int = 30,
        **kwargs,
    ) -> "RedisConnectionManager":
        """
        Factory method to initialize and return a RedisConnectionManager instance.

        Extra keyword arguments are passed to __init__.

        Args:
            redis_url (str): Redis connection URL.
            logger: Optional custom logger.
            **kwargs: Extra connection parameters.

        Returns:
            RedisConnectionManager: Initialized instance (NOT yet connected).

        Raises:
            Exception: If initialization fails.
        """
        try:
            instance = cls(
                redis_url=redis_url,
                logger=logger,
                max_pool_size=max_pool_size,
                connect_timeout_ms=connect_timeout_ms,
                socket_timeout_ms=socket_timeout_ms,
                health_check_interval=health_check_interval,
                **kwargs,
            )
            
            return instance
        except Exception as e:
            loguru.logger.error(f"Failed to initialize RedisConnectionManager: {e}")
            raise

    async def connect(self) -> bool:
        """
        Establish async connection to Redis with configurable pool.

        Returns:
            bool: True on success, False on failure.
        """
        try:
            self.logger.info(
                f"Connecting to Redis | "
                f"pool max={self.max_pool_size} | "
                f"connect_timeout={self.connect_timeout_ms}ms"
            )

            self.client = redis.Redis.from_url(
                self.redis_url,
                max_connections=self.max_pool_size,
                socket_connect_timeout=self.connect_timeout_ms / 1000,
                socket_timeout=self.socket_timeout_ms / 1000,
                health_check_interval=self.health_check_interval,
                decode_responses=True,
                socket_keepalive=True,
            )

            await self.client.ping()
            self._last_health_check = time.monotonic()

            self.logger.success(f"Connected to Redis | url={self.redis_url}")
            return True

        except RedisConnectionError as e:
            self.logger.error(f"Redis connection failed: {e}")
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected connection error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    async def disconnect(self) -> bool:
        """
        Close Redis connection and cleanup resources.

        Returns:
            bool: True on success or if already disconnected.
        """
        try:
            if self.client:
                await self.client.close()
                self.client = None
                self._last_health_check = 0.0
                self.logger.info("Disconnected from Redis")
            return True
        except Exception as e:
            self.logger.error(
                f"Disconnect error: {type(e).__name__}: {e}", exc_info=True
            )
            return False

    async def reconnect(self) -> bool:
        """
        Force reconnection — used by @retry decorator between attempts.

        Returns:
            bool: True if reconnection successful.
        """
        self.logger.info("Reconnecting to Redis...")
        await self.disconnect()
        return await self.connect()

    async def ensure_connected(self) -> bool:
        """
        Validate connection with THROTTLED health checks.

        Only pings server every `health_check_interval` seconds instead of
        every operation. Redis connection pool handles most issues internally.

        Returns:
            bool: True if connected and healthy.
        """
        if self.client is None:
            self.logger.warning("No active connection, attempting to connect...")
            return await self.connect()

        # Throttle: skip ping if we recently verified connection
        now = time.monotonic()
        if now - self._last_health_check < self.health_check_interval:
            return True

        try:
            await self.client.ping()
            self._last_health_check = now
            return True
        except (RedisConnectionError, Exception) as e:
            self.logger.warning(
                f"Health check failed ({type(e).__name__}), reconnecting..."
            )
            return await self.reconnect()

    async def __aenter__(self):
        """Async context manager entry - establishes connection."""
        if not await self.connect():
            raise ConnectionError("Failed to establish Redis connection")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - closes connection."""
        await self.disconnect()
        return False

    @staticmethod
    def retry(
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        backoff_factor: float = 2.0,
        exceptions: tuple = RETRYABLE_ERRORS,
    ) -> Callable:
        """
        Retry decorator for async methods with exponential backoff.

        Retries on transient errors (network, timeouts, auto-reconnects).
        Does NOT retry on programming errors.

        Between retries, attempts to reconnect via `self.conn.reconnect()`
        (for DDL/DML classes) or `self.reconnect()` (for ConnectionManager itself).

        Args:
            max_attempts (int): Maximum retry attempts. Default 3.
            base_delay (float): Initial delay in seconds. Default 0.1.
            max_delay (float): Cap for exponential delay. Default 5.0.
            backoff_factor (float): Multiplier for delay. Default 2.0.
            exceptions (tuple): Exception types to retry. Default retryable errors.

        Returns:
            Callable: Decorator function.
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(self, *args, **kwargs):
                conn = getattr(self, "conn", None) or self
                delay = base_delay
                last_exception = None

                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(self, *args, **kwargs)

                    except exceptions as e:
                        last_exception = e

                        if attempt == max_attempts:
                            self.logger.error(
                                f"[retry] {func.__name__} FAILED after "
                                f"{max_attempts} attempts | {type(e).__name__}: {e}"
                            )
                            raise

                        self.logger.warning(
                            f"[retry] {func.__name__} attempt "
                            f"{attempt}/{max_attempts} failed: {type(e).__name__}. "
                            f"Retrying in {delay:.2f}s..."
                        )

                        # Try to reconnect before next attempt
                        try:
                            await conn.reconnect()
                        except Exception as reconnect_err:
                            self.logger.warning(
                                f"[retry] reconnect failed: "
                                f"{type(reconnect_err).__name__}: {reconnect_err}"
                            )

                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)

                    except Exception as e:
                        # Non-retryable error - re-raise immediately
                        self.logger.error(
                            f"Non-retryable error in {func.__name__}: "
                            f"{type(e).__name__}: {e}",
                            exc_info=True,
                        )
                        raise

                # Safety net (should never reach here)
                raise last_exception  # pragma: no cover

            return wrapper

        return decorator
    

retry=RedisConnectionManager.retry


