"""
Async MongoDB DML (Data Manipulation Language) operations.

Handles CRUD operations: insert, get, update, delete, stream.
All public operations (except async generators) are wrapped with @retry.

Version: 3.0.0
"""

from typing import Optional, Dict, List, Any, AsyncGenerator

import pymongo
import loguru
from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError, BulkWriteError

from .async_connection import MongoConnectionManager, retry
from .mongo_utility import UpdateOperation
from DatabaseInfrastructure.Interfaces.document_dml import DocumentInterfaceDML

class MongoDML(DocumentInterfaceDML):
    """
    MongoDB DML operations - CRUD and data manipulation.

    All operations wrapped with retry logic for transient failures.
    Duplicate key errors are NOT retried (they're expected in scraping).

    Attributes:
        conn (ConnectionManager): The connection manager instance.
        logger: Logger instance (inherited from connection).
    """

    def __init__(
        self,
        connection: MongoConnectionManager,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize DML handler.

        Args:
            connection (ConnectionManager): Active connection manager instance.
            logger: Optional custom logger (defaults to connection's logger).
        """
        if connection is None:
            raise ValueError("ConnectionManager instance is required")

        self.conn = connection
        self.logger = logger if logger is not None else connection.logger

        self.logger.info("MongoDML initialized")

    @classmethod
    async def init_class(
        cls,
        connection: MongoConnectionManager,
        logger: Optional[Any] = None,
    ) -> "MongoDML":
        """
        Factory method to initialize and return a MongoDML instance.

        Args:
            connection (ConnectionManager): Active connection manager instance.
            logger: Optional custom logger.

        Returns:
            MongoDML: Initialized DML handler.

        Raises:
            Exception: If initialization fails.
        """
        try:
            instance = cls(connection, logger)
            return instance
        except Exception as e:
            loguru.logger.error(f"Failed to initialize MongoDML: {e}")
            raise

    @property
    def cleint(self):
        if not self.conn:
            raise ("Please Proivde Connection First") 
        return self.conn.client

    # ==================== INSERT ====================

    @retry()
    async def insert_one(
        self,
        collection_name: str,
        document: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Insert single document. Silent on success (logs at DEBUG).

        Args:
            collection_name (str): Target collection.
            document (Dict): Document to insert.

        Returns:
            Optional[Any]: Inserted _id on success, None on duplicate/error.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - insert into '{collection_name}' failed"
                )
                return None

            result = await self.db[collection_name].insert_one(document)
            self.logger.debug(
                f"Inserted _id={result.inserted_id} into '{collection_name}'"
            )
            return result.inserted_id

        except DuplicateKeyError:
            # Expected in scraping - not retried, logged at DEBUG
            self.logger.debug(f"Duplicate skipped in '{collection_name}'")
            return None
        except Exception as e:
            self.logger.error(
                f"Insert error in '{collection_name}': {type(e).__name__}: {e}",
                exc_info=True,
            )
            return None

    @retry()
    async def insert_many(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> Optional[List[Any]]:
        """
        Insert multiple documents in batches with duplicate tolerance.
        Compact logging - one start log, DEBUG per batch, one summary.

        Args:
            collection_name (str): Target collection.
            documents (List[Dict]): Documents to insert.
            batch_size (int): Batch size. Default 1000.

        Returns:
            Optional[List[Any]]: List of inserted _ids. None on critical failure.
        """
        if not documents:
            self.logger.debug(
                f"insert_many skipped (empty) | collection='{collection_name}'"
            )
            return []

        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"insert_many aborted (not connected) | collection='{collection_name}'"
                )
                return None

            total_docs = len(documents)
            total_batches = (total_docs + batch_size - 1) // batch_size
            inserted_count = 0
            inserted_ids: List[Any] = []
            failed_batches = 0
            duplicate_errors = 0
            other_errors = 0

            self.logger.info(
                f"insert_many started | collection='{collection_name}' | "
                f"docs={total_docs} | batches={total_batches}"
            )

            for batch_num, start in enumerate(range(0, total_docs, batch_size), 1):
                batch = documents[start:start + batch_size]

                try:
                    result = await self.db[collection_name].insert_many(
                        batch, ordered=False
                    )
                    batch_inserted = len(result.inserted_ids)
                    inserted_count += batch_inserted
                    inserted_ids.extend(result.inserted_ids)

                    self.logger.debug(
                        f"Batch {batch_num}/{total_batches} inserted={batch_inserted}"
                    )

                except BulkWriteError as e:
                    batch_inserted = e.details.get("nInserted", 0)
                    inserted_count += batch_inserted
                    write_errors = e.details.get("writeErrors", [])

                    # Aggregate counters instead of logging each error
                    batch_dups = 0
                    batch_others = 0
                    for err in write_errors:
                        if err.get("code") == 11000:
                            batch_dups += 1
                        else:
                            batch_others += 1
                    duplicate_errors += batch_dups
                    other_errors += batch_others

                    # Only log if there are NON-duplicate errors (real issues)
                    if batch_others > 0:
                        sample = next(
                            (err for err in write_errors if err.get("code") != 11000),
                            write_errors[0],
                        )
                        self.logger.warning(
                            f"Batch {batch_num}/{total_batches} write errors | "
                            f"inserted={batch_inserted} | duplicates={batch_dups} | "
                            f"other={batch_others} | sample_code={sample.get('code')} | "
                            f"sample_msg={str(sample.get('errmsg', ''))[:100]}"
                        )
                    else:
                        self.logger.debug(
                            f"Batch {batch_num}/{total_batches} | "
                            f"inserted={batch_inserted} | duplicates={batch_dups}"
                        )

                except Exception as e:
                    failed_batches += 1
                    self.logger.error(
                        f"Batch {batch_num}/{total_batches} failed | "
                        f"{type(e).__name__}: {e}",
                        exc_info=True,
                    )

            # ONE clear summary log
            duplicate_count = total_docs - inserted_count - other_errors

            if failed_batches > 0 or other_errors > 0:
                level = "warning"
            elif inserted_count == total_docs:
                level = "success"
            elif inserted_count > 0:
                level = "info"
            else:
                level = "warning"

            getattr(self.logger, level)(
                f"insert_many done | collection='{collection_name}' | "
                f"provided={total_docs} | inserted={inserted_count} | "
                f"duplicates={duplicate_count} | errors={other_errors} | "
                f"failed_batches={failed_batches}"
            )

            return inserted_ids

        except Exception as e:
            self.logger.critical(
                f"insert_many critical failure | collection='{collection_name}' | "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return None

    # ==================== READ ====================

    @retry()
    async def get_one(
        self,
        collection_name: str,
        query: Optional[Dict[str, Any]] = None,
        projection: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch single document. Silent on success.

        Args:
            collection_name (str): Target collection.
            query (Optional[Dict]): Query filter. Defaults to {}.
            projection (Optional[Dict]): Field projection.

        Returns:
            Optional[Dict]: Document or None.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - get_one from '{collection_name}' failed"
                )
                return None

            return await self.db[collection_name].find_one(query or {}, projection)

        except Exception as e:
            self.logger.error(
                f"get_one error: {type(e).__name__}: {e}", exc_info=True
            )
            return None

    async def stream_many_docs(
        self,
        collection_name: str,
        query: Optional[Dict[str, Any]] = None,
        projection: Optional[Dict[str, Any]] = None,
        batch_size: int = 1000,
        sort_ascending: bool = True,
        resume_after: Optional[Any] = None,
    ) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """
        Stream documents in ordered batches.

        NOTE: Not decorated with @retry because async generators can't be
        cleanly retried mid-iteration. Use `resume_after` for manual resume.

        Args:
            collection_name (str): Target collection.
            query (Optional[Dict]): Query filter.
            projection (Optional[Dict]): Field projection.
            batch_size (int): Docs per yielded batch. Default 1000.
            sort_ascending (bool): Sort by _id direction. Default True.
            resume_after (Optional[Any]): _id to resume from.

        Yields:
            List[Dict]: Batches of documents.
        """
        if query is None:
            query = {}

        if resume_after is not None:
            op = "$gt" if sort_ascending else "$lt"
            query = (
                {"$and": [query, {"_id": {op: resume_after}}]}
                if query
                else {"_id": {op: resume_after}}
            )

        sort_order = pymongo.ASCENDING if sort_ascending else pymongo.DESCENDING

        try:
            if not await self.conn.ensure_connected():
                raise ConnectionError("Database not connected")

            self.logger.info(
                f"Stream started | collection='{collection_name}' | "
                f"batch_size={batch_size} | resume_after={resume_after}"
            )

            cursor = (
                self.db[collection_name]
                .find(query, projection)
                .sort("_id", sort_order)
                .batch_size(batch_size)
            )

            batch: List[Dict[str, Any]] = []
            doc_count = 0
            batch_count = 0
            LOG_EVERY_N_BATCHES = 10  # Sample progress logs

            async for doc in cursor:
                batch.append(doc)
                doc_count += 1

                if len(batch) >= batch_size:
                    batch_count += 1
                    if batch_count % LOG_EVERY_N_BATCHES == 0:
                        self.logger.debug(
                            f"Stream progress | batches={batch_count} | docs={doc_count}"
                        )
                    yield batch
                    batch = []

            if batch:
                yield batch

            self.logger.info(
                f"Stream complete | collection='{collection_name}' | docs={doc_count}"
            )

        except ConnectionError as e:
            self.logger.error(f"Stream connection lost '{collection_name}': {e}")
            raise
        except Exception as e:
            self.logger.error(
                f"Stream error '{collection_name}': {type(e).__name__}: {e}",
                exc_info=True,
            )
            raise

    async def get_many(
        self,
        collection_name: str,
        query: Optional[Dict[str, Any]] = None,
        projection: Optional[Dict[str, Any]] = None,
        batch_size: int = 3000,
        sort_ascending: bool = True,
        resume_after: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all documents matching query (uses streaming internally).

        Args:
            collection_name (str): Target collection.
            query (Optional[Dict]): Query filter.
            projection (Optional[Dict]): Field projection.
            batch_size (int): Batch size. Default 3000.
            sort_ascending (bool): Sort direction.
            resume_after (Optional[Any]): _id to resume from.

        Returns:
            List[Dict]: All matching documents.
        """
        all_docs = []
        async for batch in self.stream_many_docs(
            collection_name, query, projection, batch_size, sort_ascending, resume_after
        ):
            all_docs.extend(batch)
        return all_docs

    # ==================== UPDATE ====================

    @retry()
    async def update_one(
        self,
        collection_name: str,
        query: Dict[str, Any],
        update: Dict[str, Any],
    ) -> bool:
        """
        Update single document with upsert. Silent on success.

        Args:
            collection_name (str): Target collection.
            query (Dict): Match filter.
            update (Dict): Update operations (e.g., {"$set": {...}}).

        Returns:
            bool: True if matched or upserted.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - cannot update '{collection_name}'"
                )
                return False

            result = await self.db[collection_name].update_one(
                query, update, upsert=True
            )

            self.logger.debug(
                f"update_one '{collection_name}' | matched={result.matched_count} | "
                f"modified={result.modified_count} | upserted={bool(result.upserted_id)}"
            )
            return result.matched_count > 0 or result.upserted_id is not None

        except Exception as e:
            self.logger.error(
                f"update_one error '{collection_name}': {type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    @retry()
    async def update_many(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
        key_field: str,
        operations: Dict[UpdateOperation, Dict[str, Any]],
        batch_size: int = 1000,
    ) -> bool:
        """
        Bulk upsert with flexible schema operations. Compact logging.

        Args:
            collection_name (str): Target collection.
            documents (List[Dict]): Documents to upsert.
            key_field (str): Field for matching.
            operations (Dict[UpdateOperation, Dict]): Op → field mapping.
            batch_size (int): Batch size. Default 1000.

        Returns:
            bool: True if operation completed.
        """
        if not documents:
            self.logger.debug(
                f"update_many skipped (empty) | collection='{collection_name}'"
            )
            return False

        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - cannot update_many '{collection_name}'"
                )
                return False

            collection = self.db[collection_name]
            total_docs = len(documents)
            total_batches = (total_docs + batch_size - 1) // batch_size

            # Aggregate counters
            total_matched = 0
            total_modified = 0
            total_upserted = 0
            skipped_docs = 0
            failed_batches = 0
            batches_with_errors = 0

            self.logger.info(
                f"update_many started | collection='{collection_name}' | "
                f"docs={total_docs} | batches={total_batches}"
            )

            for batch_num, i in enumerate(range(0, total_docs, batch_size), 1):
                batch = documents[i:i + batch_size]
                ops_list = []

                for doc in batch:
                    if key_field not in doc:
                        skipped_docs += 1
                        continue

                    update_doc = self._build_update_doc(doc, operations)

                    if update_doc:
                        ops_list.append(
                            UpdateOne(
                                {key_field: doc[key_field]},
                                update_doc,
                                upsert=True,
                            )
                        )

                if not ops_list:
                    continue

                try:
                    result = await collection.bulk_write(ops_list, ordered=False)
                    total_matched += result.matched_count
                    total_modified += result.modified_count
                    total_upserted += len(result.upserted_ids)

                    self.logger.debug(
                        f"Batch {batch_num}/{total_batches} | "
                        f"matched={result.matched_count} | "
                        f"modified={result.modified_count} | "
                        f"upserted={len(result.upserted_ids)}"
                    )

                except BulkWriteError as e:
                    batches_with_errors += 1
                    write_errors = e.details.get("writeErrors", [])
                    self.logger.warning(
                        f"Batch {batch_num}/{total_batches} bulk write errors="
                        f"{len(write_errors)}"
                    )

                except Exception as e:
                    failed_batches += 1
                    self.logger.error(
                        f"Batch {batch_num}/{total_batches} failed | "
                        f"{type(e).__name__}: {e}",
                        exc_info=True,
                    )

            # One clear summary
            level = (
                "warning"
                if (failed_batches or batches_with_errors or skipped_docs)
                else "success"
            )
            getattr(self.logger, level)(
                f"update_many done | collection='{collection_name}' | "
                f"matched={total_matched} | modified={total_modified} | "
                f"upserted={total_upserted} | skipped={skipped_docs} | "
                f"failed_batches={failed_batches} | error_batches={batches_with_errors}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"update_many critical error '{collection_name}': "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return False


    # ==================== DELETE ====================

    @retry()
    async def delete_one(
        self,
        collection_name: str,
        query: Dict[str, Any],
    ) -> bool:
        """
        Delete single document matching query. Silent on success.

        Args:
            collection_name (str): Target collection.
            query (Dict): Match filter.

        Returns:
            bool: True if a document was deleted.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - delete_one from '{collection_name}' failed"
                )
                return False

            result = await self.db[collection_name].delete_one(query)

            self.logger.debug(
                f"delete_one '{collection_name}' | deleted={result.deleted_count}"
            )
            return result.deleted_count > 0

        except Exception as e:
            self.logger.error(
                f"delete_one error '{collection_name}': {type(e).__name__}: {e}",
                exc_info=True,
            )
            return False

    @retry()
    async def delete_many(
        self,
        collection_name: str,
        query: Dict[str, Any],
        batch_size: int = 1000,
    ) -> Optional[int]:
        """
        Delete multiple documents matching query in batches with compact logging.

        NOTE: Uses bulk delete via `delete_many()` per batch if query is a list,
        or single `delete_many()` for a single query. For simplicity, this
        handles a single query filter across the entire collection.

        Args:
            collection_name (str): Target collection.
            query (Dict): Match filter for documents to delete.
            batch_size (int): Ignored for single query; kept for API consistency.

        Returns:
            Optional[int]: Number of documents deleted, or None on critical failure.
        """
        try:
            if not await self.conn.ensure_connected():
                self.logger.error(
                    f"Not connected - delete_many from '{collection_name}' failed"
                )
                return None

            self.logger.info(
                f"delete_many started | collection='{collection_name}'"
            )

            result = await self.db[collection_name].delete_many(query)

            deleted_count = result.deleted_count

            level = "success" if deleted_count > 0 else "info"
            getattr(self.logger, level)(
                f"delete_many done | collection='{collection_name}' | "
                f"deleted={deleted_count}"
            )

            return deleted_count

        except Exception as e:
            self.logger.error(
                f"delete_many error '{collection_name}': {type(e).__name__}: {e}",
                exc_info=True,
            )
            return None


    # ==================== HELPERS ====================

    def _build_update_doc(
        self,
        doc: Dict[str, Any],
        operations: Dict[UpdateOperation, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build MongoDB update document from operations mapping.
        Extracted for readability AND to make update_many easier to reason about.

        Args:
            doc (Dict): Source document with values.
            operations (Dict[UpdateOperation, Dict]): Operations to apply.

        Returns:
            Dict: MongoDB update document (e.g., {"$set": {...}, "$push": {...}}).
        """
        update_doc = {}

        for op, field_mapping in operations.items():
            if op == UpdateOperation.SET:
                set_fields = {
                    t: doc[s] for t, s in field_mapping.items() if s in doc
                }
                if set_fields:
                    update_doc["$set"] = set_fields

            elif op == UpdateOperation.PUSH_BOUNDED:
                push_fields = {
                    t: {"$each": [doc[s]], "$slice": -10000}
                    for t, s in field_mapping.items()
                    if s in doc
                }
                if push_fields:
                    update_doc["$push"] = push_fields

            elif op == UpdateOperation.PUSH:
                push_fields = {
                    t: doc[s] for t, s in field_mapping.items() if s in doc
                }
                if push_fields:
                    update_doc["$push"] = push_fields

            elif op == UpdateOperation.CURRENT_DATE:
                update_doc["$currentDate"] = field_mapping

            elif op == UpdateOperation.SET_ON_INSERT:
                soi = {}
                for t, s in field_mapping.items():
                    if s in doc:
                        soi[t] = doc[s]
                    elif t in doc:
                        soi[t] = doc[t]
                if soi:
                    update_doc["$setOnInsert"] = soi

            elif op == UpdateOperation.UNSET:
                update_doc["$unset"] = field_mapping

            elif op == UpdateOperation.INC:
                update_doc["$inc"] = field_mapping

        return update_doc
    



