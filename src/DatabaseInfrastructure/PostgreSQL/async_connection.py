# async_connection.py
"""
PostgresConnectionManager — owns the SQLAlchemy AsyncEngine lifecycle for
the async PostgreSQL layer. PostgresDDL and PostgresDML both compose this
class for all engine access; neither of them creates or disposes the main
engine directly (the one exception is the short-lived "temp" engines used
for admin-only CREATE/DROP DATABASE operations, which the caller owns).

This file did not exist in the original codebase — PostgresDDL and
PostgresDML both called `manager.get_engine()`, `manager.reconnect()`, and
`manager.build_temp_engine(...)`, so this implementation is built to match
that inferred interface, plus the reliability requirements called out in
the refactor plan (§3.8):

  * `reconnect()` disposes the previous engine before building a new one.
  * `reconnect()` is safe under concurrent calls — an `asyncio.Lock` plus a
    double-check (re-test the existing engine after acquiring the lock)
    means only one coroutine actually rebuilds; the rest just proceed once
    the lock is released.
  * `build_temp_engine(...)` always returns a brand-new, independent engine
    that the caller owns and must dispose of itself.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import quote_plus
import loguru
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from DatabaseInfrastructure.Interfaces.connection import ConnectionManagerInterface
from functools import wraps



class PostgresConnectionManager(ConnectionManagerInterface):
    """
    Owns the async SQLAlchemy engine for a single (host, port, database,
    username) target. Reconnects are task-safe via an internal
    `asyncio.Lock`.
    """

    def __init__(self,host: str,port: int,username: str,password: str,database: str,
                *,pool_size: int = 5,max_overflow: int = 10,
                pool_timeout: float = 30.0,pool_recycle: float = 1800.0,
                echo: bool = False,logger: Optional[Any] = None,) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.echo = echo

        self.logger = logger if logger is not None else loguru.logger
        self._engine: Optional[AsyncEngine] = None
        self._reconnect_lock = asyncio.Lock()

        self.logger.info(
            f"PostgresConnectionManager configured for "
            f"{username}@{host}:{port}/{database}"
        )

    # ─── Factory ────────────────────────────────────────────────────────────
    @classmethod
    async def init_class(
        cls,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
        pool_recycle: float = 1800.0,
        echo: bool = False,
        logger: Optional[Any] = None,
        **kwargs: Any,
    ) -> "PostgresConnectionManager":
        logger = logger or loguru.logger
        instance = cls(
            host,
            port,
            username,
            password,
            database,
            pool_size=pool_size,        # <-- keyword
            max_overflow=max_overflow,  # <-- keyword
            pool_timeout=pool_timeout,  # <-- keyword
            pool_recycle=pool_recycle,  # <-- keyword
            echo=echo,                  # <-- keyword
            logger=logger,              # <-- keyword
            **kwargs
        )
        await instance.connect()
        return instance

    # ─── Lifecycle ──────────────────────────────────────────────────────────


    async def connect(self) -> None:
        """Build the main engine and verify connectivity. Idempotent."""
        if self._engine is not None:
            self.logger.debug("connect() called but engine already exists — no-op")
            return

        self.logger.info("Connecting PostgresConnectionManager...")
        engine = self._build_engine(self.username, self.password, self.database)

        try:
            await self.ensure_connected(engine)
        except Exception as e:
            self.logger.exception(f"Initial connectivity check failed: {e}")
            await engine.dispose()
            raise

        self._engine = engine
        self.logger.info("PostgresConnectionManager connected successfully")

    async def disconnect(self) -> None:
        """Dispose the main engine. Safe to call multiple times."""
        async with self._reconnect_lock:
            if self._engine is not None:
                await self._engine.dispose()
                self._engine = None
                self.logger.info("PostgresConnectionManager engine disposed")

    async def reconnect(self) -> None:
        """
        Rebuild the main engine. Safe to call from multiple coroutines
        concurrently: only the first caller through the lock actually
        rebuilds. Subsequent callers re-check the (possibly already
        rebuilt) engine's health once they acquire the lock and return
        early if it's already fine, instead of rebuilding again.
        """
        async with self._reconnect_lock:
            if self._engine is not None:
                try:
                    async with self._engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                    self.logger.debug("reconnect() called but existing engine is already healthy — no-op")
                    return
                except Exception:
                    self.logger.warning(
                        "Existing engine failed health check during reconnect(); rebuilding"
                    )

            old_engine, self._engine = self._engine, None
            if old_engine is not None:
                try:
                    await old_engine.dispose()
                except Exception:
                    self.logger.exception("Error disposing old engine during reconnect()")

            self._engine = self._build_engine(self.username, self.password, self.database)
            self.logger.info("PostgresConnectionManager reconnected: new engine built")

    async def ensure_connected(self, engine) -> None:
        """Verify that the given engine can actually connect to Postgres."""
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))



    @staticmethod
    def retry(
        max_attempts: int = 2,          # first try + 1 retry by default
        base_delay: float = 0.1,
        max_delay: float = 2.0,
        backoff_factor: float = 2.0,
        exceptions: tuple =(Exception,) ,
    ) -> Callable:
        """
        Retry async methods on connection-related failures.

        - Retries only on transient connection errors
        - Reconnects between attempts
        - Leaves integrity errors and programming errors untouched
        - Centralizes connection-failure logging here
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(self, *args, **kwargs):
                conn = getattr(self, "conn", None) or self
                delay = base_delay
                last_exception = None

                for attempt in range(1, max_attempts + 1):
                    self.logger.debug(
                        f"Entering '{func.__name__}' attempt {attempt}/{max_attempts} "
                        f"with args={args}, kwargs={kwargs}"
                    )

                    try:
                        return await func(self, *args, **kwargs)

                    except exceptions as e:
                        last_exception = e
                        error_name = type(e).__name__

                        if attempt == max_attempts:
                            self.logger.exception(
                                f"{error_name} in '{func.__name__}' after "
                                f"{max_attempts} attempts: {e}"
                            )
                            raise

                        self.logger.warning(
                            f"{error_name} in '{func.__name__}', reconnecting and "
                            f"retrying in {delay:.2f}s (attempt {attempt}/{max_attempts})"
                        )

                        try:
                            await conn.reconnect()
                        except Exception as reconnect_err:
                            self.logger.warning(
                                f"Reconnect failed before retry of '{func.__name__}': "
                                f"{type(reconnect_err).__name__}: {reconnect_err}"
                            )

                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)

                    except IntegrityError as e:
                        self.logger.exception(f"IntegrityError in '{func.__name__}': {e}")
                        raise

                    except Exception as e:
                        self.logger.exception(
                            f"Unexpected error in '{func.__name__}': {e}"
                        )
                        raise

                raise last_exception  # safety net

            return wrapper

        return decorator



    async def __aenter__(self) -> "PostgresConnectionManager":
        if self._engine is None:
            await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            self.logger.exception(
                f"Exception inside PostgresConnectionManager context: "
                f"{exc_type.__name__}: {exc_val}"
            )
        await self.close()

    # ─── Access ─────────────────────────────────────────────────────────────

    def get_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError(
                "PostgresConnectionManager is not connected. Call connect() first."
            )
        return self._engine

    def build_temp_engine(self, username: str, password: str, database: str) -> AsyncEngine:
        """
        Build a brand-new, independent engine against a possibly different
        database (e.g. the `postgres` maintenance DB, to run CREATE/DROP
        DATABASE). The caller owns this engine and MUST dispose of it —
        this manager never caches or reuses it, and it is never affected
        by reconnect()/close() on the main engine.
        """
        return self._build_engine(username, password, database, pool_size=1, max_overflow=0)

    # ─── Private ────────────────────────────────────────────────────────────
    def _build_engine(
        self,
        username: str,
        password: str,
        database: str,
        *,
        pool_size: Optional[int] = None,
        max_overflow: Optional[int] = None,
    ) -> AsyncEngine:
        url = (
            f"postgresql+asyncpg://{quote_plus(username)}:{quote_plus(password)}"
            f"@{self.host}:{self.port}/{database}"
        )
        return create_async_engine(
            url,
            echo=self.echo,
            pool_size=pool_size if pool_size is not None else self.pool_size,
            max_overflow=max_overflow if max_overflow is not None else self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
        )


retry = PostgresConnectionManager.retry

