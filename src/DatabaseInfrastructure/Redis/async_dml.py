from typing import Any, AsyncGenerator, Dict, List, Optional
from contextlib import asynccontextmanager
import asyncio

import loguru
import redis.asyncio as redis
from redis.asyncio import client

from DatabaseInfrastructure.Interfaces.document_dml import DocumentInterfaceDML
from .async_connection import RedisConnectionManager, retry


class RedisDML(DocumentInterfaceDML):
    """
    Async Redis Data Manipulation Layer with pipeline batching,
    connection pooling, and proper lifecycle management.
    """

    def __init__(
        self,
        connection_manager: RedisConnectionManager,
        logger: Optional[loguru.Logger] = None,
    ):
        self.connection_manager = connection_manager
        self.logger = logger or loguru.logger
        self._client: Optional[client.Redis] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Initialize the Redis client from the connection manager."""
        if self._client is None:
            self.logger.debug("Initializing Redis client")
            self._client = await self.connection_manager.get_client()
            self.logger.info("Redis client connected")

    async def disconnect(self) -> None:
        """Gracefully close the Redis client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self.logger.info("Redis client disconnected")

    async def __aenter__(self) -> "RedisDML":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    @property
    def client(self) -> client.Redis:
        """Lazy-access client with validation."""
        if self._client is None:
            raise RuntimeError(
                "Redis client not connected. Use 'async with' or call connect() first."
            )
        return self._client

    @classmethod
    async def init_class(
        cls,
        connection_manager: RedisConnectionManager,
        logger: Optional[loguru.Logger] = None,
    ) -> "RedisDML":
        """Factory method with guaranteed connection."""
        instance = cls(connection_manager, logger)
        await instance.connect()
        return instance

    # ── Insert ─────────────────────────────────────────────────────────────

    @retry()
    async def insert_one(
        self,
        key: str,
        document: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Insert/overwrite fields of a single hash document. Returns True on success.

        This is the single source of truth for HSET — retry, logging, and
        exception handling live here. Other methods (e.g. update_one) call
        this instead of touching self.client.hset directly.

        Args:
            ttl: if provided, expiration in seconds applied via set_ttl()
                 right after the HSET succeeds. A failed TTL set does not
                 fail the insert — the document is written either way; it's
                 logged as a warning instead.
        """
        try:
            self.logger.debug(f"Inserting document to key: {key}")
            await self.client.hset(key, mapping=document)

            if ttl is not None:
                ttl_ok = await self.set_ttl(key, ttl)
                if not ttl_ok:
                    self.logger.warning(
                        f"Document inserted but TTL not set for key '{key}'"
                    )

            return True
        except Exception as e:
            self.logger.exception(f"Error inserting key '{key}': {e}")
            return False

    async def insert_many(
        self,
        keys: List[str],
        documents: List[Dict[str, Any]],
        batch_size: int = 500,
        ttl: Optional[int] = None,
    ) -> int:
        """
        Bulk insert using pipelining for performance.
        Returns count of successfully inserted documents.

        Args:
            ttl: if provided, applied to every key in the batch via
                 set_ttl(), fanned out concurrently with asyncio.gather
                 after each pipeline's HSETs complete. Trade-off: this reuses
                 set_ttl for consistency but costs N extra round trips per
                 batch (one EXPIRE per key) instead of folding EXPIRE into
                 the same HSET pipeline. If TTL-heavy bulk inserts become a
                 bottleneck, that's the place to optimize
                 (pipe.expire(k, ttl) inline, same pipeline).
        """
        if len(keys) != len(documents):
            raise ValueError("Keys and documents must have the same length")

        self.logger.info(f"Bulk inserting {len(keys)} documents")
        inserted = 0

        # Process in pipeline batches to avoid memory bloat
        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]

            async with self.client.pipeline(transaction=False) as pipe:
                for k, doc in zip(batch_keys, batch_docs):
                    pipe.hset(k, mapping=doc)
                results = await pipe.execute()

            inserted += sum(1 for r in results if r is not None)

            if ttl is not None:
                await asyncio.gather(
                    *(self.set_ttl(k, ttl) for k in batch_keys),
                    return_exceptions=True,
                )

        self.logger.info(f"Successfully inserted {inserted}/{len(keys)} documents")
        return inserted

    # ── TTL ────────────────────────────────────────────────────────────────

    @retry()
    async def set_ttl(self, key: str, duration_seconds: int) -> bool:
        """
        Set/refresh an expiration on an existing key.
        Returns True if the TTL was set (key existed), False otherwise.
        """
        try:
            result = await self.client.expire(key, duration_seconds)
            if result:
                self.logger.debug(f"Set TTL={duration_seconds}s on key '{key}'")
                return True
            self.logger.warning(f"Could not set TTL on '{key}' — key does not exist")
            return False
        except Exception as e:
            self.logger.exception(f"Error setting TTL on key '{key}': {e}")
            return False

    @retry()
    async def get_ttl(self, key: str) -> Optional[int]:
        """
        Get remaining TTL in seconds for a key.
        Returns None if the key doesn't exist, or has no expiration set
        (i.e. it persists indefinitely).
        """
        try:
            ttl = await self.client.ttl(key)
            # redis-py semantics: -2 = key doesn't exist, -1 = no TTL set
            if ttl == -2:
                self.logger.warning(f"Key '{key}' does not exist")
                return None
            if ttl == -1:
                self.logger.debug(f"Key '{key}' has no TTL set (persists)")
                return None
            return ttl
        except Exception as e:
            self.logger.exception(f"Error getting TTL for key '{key}': {e}")
            return None

    # ── Read ───────────────────────────────────────────────────────────────

    @retry()
    async def get_one(
        self,
        key: str,
        field: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Retrieve a hash document or a specific field.
        Returns None if key/field not found.
        """
        try:
            if field is None:
                return await self.client.hgetall(key)
            return await self.client.hget(key, field)
        except Exception as e:
            self.logger.exception(f"Error retrieving key '{key}': {e}")
            return None

    async def get_many(
        self,
        keys: List[str],
        batch_size: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Bulk retrieve using pipelining.
        Returns list of documents (skips missing keys).
        """
        if not keys:
            return []

        results: List[Dict[str, Any]] = []

        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]

            async with self.client.pipeline(transaction=False) as pipe:
                for k in batch:
                    pipe.hgetall(k)
                batch_results = await pipe.execute()

            for doc in batch_results:
                if doc:  # Skip empty/missing keys
                    results.append(doc)

        return results

    async def stream_many_docs(
        self,
        pattern: str = "*",
        batch_size: int = 1000,
    ) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """
        Memory-efficient streaming with SCAN + pipeline batching.
        Only holds ~batch_size documents in memory at any time.
        """
        key_buffer: List[str] = []

        async for key in self.client.scan_iter(match=pattern, count=batch_size):
            key_buffer.append(key)

            # When we have enough keys, pipeline all hgetall at once
            if len(key_buffer) >= batch_size:
                async with self.client.pipeline(transaction=False) as pipe:
                    for k in key_buffer:
                        pipe.hgetall(k)
                    docs = await pipe.execute()

                # Filter empty and yield
                batch = [d for d in docs if d]
                if batch:
                    yield batch

                key_buffer = []  # Clear references for GC

        # Flush remaining keys
        if key_buffer:
            async with self.client.pipeline(transaction=False) as pipe:
                for k in key_buffer:
                    pipe.hgetall(k)
                docs = await pipe.execute()

            batch = [d for d in docs if d]
            if batch:
                yield batch

    async def get_many_by_pattern(
        self,
        pattern: str = "*",
        batch_size: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Eagerly fetch every document whose key matches `pattern`.

        Thin wrapper around stream_many_docs() — collects all yielded
        batches into a single list. Convenient when the caller wants a
        materialized result, but note this holds the *entire* matched
        result set in memory at once.

        For large keyspaces where the match count could be large/unbounded,
        prefer iterating stream_many_docs() directly instead of this method.

        Args:
            pattern: glob-style key pattern (same as SCAN MATCH), e.g. "user:*"
            batch_size: SCAN/pipeline batch size, forwarded to stream_many_docs()
        """
        results: List[Dict[str, Any]] = []
        async for batch in self.stream_many_docs(pattern=pattern, batch_size=batch_size):
            results.extend(batch)
        return results

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_one(
        self,
        key: str,
        document: Dict[str, Any],
        merge: bool = True,
        upsert: bool = False,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Update a hash document.

        Args:
            key: Redis key to update
            document: Fields to update
            merge: If True, merges with existing fields. If False, replaces entire hash.
            upsert: If True, creates the key if it doesn't exist.
            ttl: if provided, forwarded straight through to insert_one(), which
                 applies it via set_ttl() after the write succeeds.

        Note:
            No @retry / try-except here anymore — every branch below delegates
            to insert_one() and/or delete_one(), which already carry retry,
            logging, and exception handling. This avoids double-retrying and
            double-logging the same underlying HSET/DELETE call.
        """
        exists = await self.client.exists(key)

        if not exists and not upsert:
            self.logger.warning(f"Key '{key}' not found. Set upsert=True to create.")
            return False

        if merge and exists:
            # HSET with mapping updates existing fields and adds new ones
            # without deleting missing fields (true merge behavior)
            return await self.insert_one(key, document, ttl=ttl)

        # Replace path: wipe existing hash first (if any), then write fresh
        if exists:
            deleted = await self.delete_one(key)
            if not deleted:
                self.logger.warning(f"Replace update failed: could not delete '{key}'")
                return False

        success = await self.insert_one(key, document, ttl=ttl)
        if success:
            self.logger.debug(f"Updated key '{key}' (merge={merge}, upsert={upsert})")
        return success

    async def update_many(
        self,
        keys: List[str],
        documents: List[Dict[str, Any]],
        merge: bool = True,
        upsert: bool = False,
        batch_size: int = 500,
        ttl: Optional[int] = None,
    ) -> int:
        """
        Bulk update with pipelining. Returns count of successful updates.

        Args:
            ttl: if provided, forwarded to each update_one() call, which in
                 turn forwards it to insert_one() / set_ttl().
        """
        if len(keys) != len(documents):
            raise ValueError("Keys and documents must have the same length")

        updated = 0
        for i in range(0, len(keys), batch_size):
            batch_keys = keys[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]

            # Run updates concurrently within each batch
            tasks = [
                self.update_one(k, d, merge=merge, upsert=upsert, ttl=ttl)
                for k, d in zip(batch_keys, batch_docs)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            updated += sum(1 for r in results if r is True)

        return updated

    # ── Delete ─────────────────────────────────────────────────────────────

    @retry()
    async def delete_one(self, key: str) -> bool:
        """
        Delete a single key. Returns True if key existed and was deleted.

        Single source of truth for DELETE — retry, logging, and exception
        handling live here. delete_many() calls this per key instead of
        issuing a raw client.delete(*batch) call.
        """
        try:
            result = await self.client.delete(key)
            if result > 0:
                self.logger.debug(f"Deleted key '{key}'")
                return True
            self.logger.warning(f"Key '{key}' not found for deletion")
            return False
        except Exception as e:
            self.logger.exception(f"Error deleting key '{key}': {e}")
            return False

    async def delete_many(
        self,
        keys: List[str],
        batch_size: int = 500,
    ) -> int:
        """
        Bulk delete by fanning out to delete_one() per key, concurrently
        within each batch via asyncio.gather.

        Trade-off vs. a single `DEL k1 k2 ... kN` call: this issues N
        concurrent round trips per batch instead of 1, but each key gets
        independent retry + error isolation (one failing key doesn't force
        a retry of the whole batch), and all delete logging/exception
        handling stays centralized in delete_one().
        Returns count of deleted keys.
        """
        if not keys:
            return 0

        deleted_total = 0

        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]

            tasks = [self.delete_one(k) for k in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            deleted_total += sum(1 for r in results if r is True)

        self.logger.info(f"Deleted {deleted_total}/{len(keys)} keys")
        return deleted_total

