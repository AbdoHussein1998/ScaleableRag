"""
Async MongoDB DDL (Data Definition Language) operations.

Handles schema-level operations: collections and indexes.
All public operations are wrapped with @retry for transient failures.

Version: 3.0.0
"""

from typing import Optional, List, Any

import loguru

from .async_connection import MongoConnectionManager, retry


class MongoDDL:
    """
    MongoDB DDL operations - schema and structure management.

    Handles collections, indexes, and other structural operations.
    All operations are wrapped with retry logic for transient failures.

    Attributes:
        conn (ConnectionManager): The connection manager instance.
        logger: Logger instance (inherited from connection).
    """

    def __init__(
        self,
        connection: ConnectionManager,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize DDL handler.

        Args:
            connection (ConnectionManager): Active connection manager instance.
            logger: Optional custom logger (defaults to connection's logger).
        """
        if connection is None:
            raise ValueError("ConnectionManager instance is required")

        self.conn = connection
        self.logger = logger if logger is not None else connection.logger

        self.logger.info("MongoDDL initialized")

    @classmethod
    async def init_class(
        cls,
        connection: ConnectionManager,
        logger: Optional[Any] = None,
    ) -> "MongoDDL":
        """
        Factory method to initialize and return a MongoDDL instance.

        Args:
            connection (ConnectionManager): Active connection manager instance.
            logger: Optional custom logger.

        Returns:
            MongoDDL: Initialized DDL handler.

        Raises:
            Exception: If initialization fails.
        """
        try:
            instance = cls(connection, logger)
            return instance
        except Exception as e:
            loguru.logger.error(f"Failed to initialize MongoDDL: {e}")
            raise

    @property
    def db(self):
        """Shortcut to the current database instance."""
        return self.conn.db

    @retry()
    async def is_collection_existed(self, collection_name: str) -> bool:
        """
        Check if collection exists. Silent unless error.

        Args:
            collection_name (str): Name of collection to check.

        Returns:
            bool: True if exists, False otherwise or on error.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(f"Not connected - cannot check '{collection_name}'")
                return False

            collections = await self.db.list_collection_names()
            return collection_name in collections

        except Exception as e:
            self.logger.error(
                f"Error checking collection '{collection_name}': "
                f"{type(e).__name__}: {e}"
            )
            return False

    @retry()
    async def create_collection(self, collection_name: str) -> bool:
        """
        Create collection (idempotent - succeeds if already exists).

        Args:
            collection_name (str): Collection to create.

        Returns:
            bool: True if created or already exists, False on error.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(f"Not connected - cannot create '{collection_name}'")
                return False

            collections = await self.db.list_collection_names()
            if collection_name in collections:
                self.logger.debug(f"Collection '{collection_name}' already exists")
                return True

            await self.db.create_collection(collection_name)
            self.logger.info(f"Created collection '{collection_name}'")
            return True

        except Exception as e:
            self.logger.error(
                f"Create collection error '{collection_name}': "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    @retry()
    async def delete_collection(self, collection_name: str) -> bool:
        """
        Drop collection from database.

        Args:
            collection_name (str): Collection to delete.

        Returns:
            bool: True if deleted, False if not found or error.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(f"Not connected - cannot delete '{collection_name}'")
                return False

            if not await self.is_collection_existed(collection_name):
                self.logger.warning(
                    f"Cannot delete - '{collection_name}' does not exist"
                )
                return False

            await self.db.drop_collection(collection_name)
            self.logger.info(f"Deleted collection '{collection_name}'")
            return True

        except Exception as e:
            self.logger.error(
                f"Delete collection error '{collection_name}': "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    @retry()
    async def create_index(self,collection_name: str,fields: List[tuple],index_name: str = None,unique: bool = False,sparse: bool = False,
    ) -> bool:
        """
        Create index on collection (idempotent).

        Args:
            collection_name (str): Target collection.
            fields (List[tuple]): List of (field, direction) tuples.
                Direction: 1 for ascending, -1 for descending.
            index_name (str): Custom index name. Auto-generated if None.
            unique (bool): Enforce uniqueness. Default False.
            sparse (bool): Sparse index. Default False.

        Returns:
            bool: True on success or if index already exists, False on error.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - cannot create index on '{collection_name}'"
                )
                return False

            if not await self.is_collection_existed(collection_name):
                self.logger.warning(
                    f"Cannot create index - '{collection_name}' does not exist"
                )
                return False

            if not index_name:
                index_name = "_".join(f"{f}_{d}" for f, d in fields)

            existing = await self.db[collection_name].index_information()
            if index_name in existing:
                self.logger.debug(
                    f"Index '{index_name}' already exists on '{collection_name}'"
                )
                return True

            await self.db[collection_name].create_index(
                fields, name=index_name, unique=unique, sparse=sparse
            )
            self.logger.info(
                f"Created index '{index_name}' on '{collection_name}' | "
                f"unique={unique} | sparse={sparse}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Create index error '{collection_name}': "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return False


        