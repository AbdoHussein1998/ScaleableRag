# src/DatabaseInfrastructure/Vector/Providers/Qdrant/qdrant_provider.py

import uuid
from typing import Optional, List, Dict, Any
from logging import Logger

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from loguru import logger as default_logger

from DatabaseInfrastructure.Vector.vector_database_interface import VectorDBInterface
from DatabaseInfrastructure.Interfaces.vector import VectorDocument


class QdrantProvider(VectorDBInterface):
    """
    Qdrant implementation of VectorDBInterface using AsyncQdrantClient.
    Fully config/controller agnostic.
    """

    DISTANCE_MAP = {
        "cosine": Distance.COSINE,
        "euclid": Distance.EUCLID,
        "dot": Distance.DOT,
        "manhattan": Distance.MANHATTAN,
    }

    def __init__(self):
        """
        Private — use init_class() instead.
        """
        self.client: Optional[AsyncQdrantClient] = None
        self.logger = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_filter(self, filters: Dict[str, Any]) -> Filter:
        """
        Converts a simple dict into a Qdrant Filter.

        Input:
            {"category": "science", "author": "john"}

        Output:
            Filter(must=[
                FieldCondition(key="category", match=MatchValue(value="science")),
                FieldCondition(key="author", match=MatchValue(value="john")),
            ])
        """
        conditions = [
            FieldCondition(
                key=key,
                match=MatchValue(value=value),
            )
            for key, value in filters.items()
        ]
        return Filter(must=conditions)

    def _point_to_document(self, point, score: float = None) -> VectorDocument:
        """
        Converts a Qdrant point/hit into a VectorDocument.
        """
        payload = dict(point.payload) if point.payload else {}
        content = payload.pop("content", "")

        return VectorDocument(
            id=str(point.id),
            content=content,
            vector=point.vector if point.vector else [],
            payload=payload,
            score=score,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def init_class(
        cls,
        url: str,
        api_key: str,
        logger: Optional[Logger] = None,
        *args,
        **kwargs,
    ) -> "QdrantProvider":
        """
        Async factory.

        Args:
            url:     Qdrant server URL
            api_key: Qdrant API key
            logger:  Optional logger — falls back to loguru if not provided
        """
        instance = cls()
        instance.logger = logger if logger is not None else default_logger

        instance.logger.info(f"Initializing QdrantProvider — url={url}")

        instance.client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
        )

        instance.logger.info("QdrantProvider initialized")
        instance.logger.success("QdrantProvider is ready to use")
        await instance.connect()
        return instance

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        try:
            await self.client.get_collections()
            self.logger.info("Connected to Qdrant server")
            self.logger.success("Qdrant connection verified")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to Qdrant: {e}")
            return False

    async def disconnect(self) -> None:
        try:
            if self.client:
                await self.client.close()
                self.client = None
                self.logger.info("Disconnected from Qdrant server")
                self.logger.success("Qdrant client closed successfully")
        except Exception as e:
            self.logger.error(f"Error disconnecting from Qdrant: {e}")

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    async def create_collection(
        self,
        collection_name: str,
        vector_dimension: int,
        distance: str = "cosine",
    ) -> bool:
        self.logger.info(f"Attempting to create collection: '{collection_name}'")

        if await self.collection_exists(collection_name):
            self.logger.warning(
                f"Collection '{collection_name}' already exists — skipping"
            )
            return False

        qdrant_distance = self.DISTANCE_MAP.get(distance.lower())
        if qdrant_distance is None:
            self.logger.error(
                f"Unsupported distance metric '{distance}'. "
                f"Supported: {list(self.DISTANCE_MAP.keys())}"
            )
            return False

        try:
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_dimension,
                    distance=qdrant_distance,
                ),
            )
            self.logger.info(
                f"Collection '{collection_name}' created — "
                f"dimension={vector_dimension}, distance={distance}"
            )
            self.logger.success(
                f"Collection '{collection_name}' created successfully"
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error creating collection '{collection_name}': {e}"
            )
            return False

    async def delete_collection(self, collection_name: str) -> bool:
        self.logger.info(f"Attempting to delete collection: '{collection_name}'")

        if not await self.collection_exists(collection_name):
            self.logger.warning(
                f"Collection '{collection_name}' does not exist — nothing to delete"
            )
            return False

        try:
            await self.client.delete_collection(collection_name)
            self.logger.info(f"Collection '{collection_name}' deleted")
            self.logger.success(
                f"Collection '{collection_name}' deleted successfully"
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error deleting collection '{collection_name}': {e}"
            )
            return False

    async def collection_exists(self, collection_name: str) -> bool:
        try:
            collections = await self.list_collections()
            exists = collection_name in collections
            self.logger.info(
                f"Collection '{collection_name}' "
                f"{'exists' if exists else 'does not exist'}"
            )
            return exists
        except Exception as e:
            self.logger.error(f"Error checking collection existence: {e}")
            return False

    async def list_collections(self) -> List[str]:
        try:
            response = await self.client.get_collections()
            names = [c.name for c in response.collections]
            self.logger.info(f"Found {len(names)} collections: {names}")
            self.logger.success("Collections listed successfully")
            return names
        except Exception as e:
            self.logger.error(f"Error listing collections: {e}")
            return []

    async def get_collection_info(self, collection_name: str) -> dict:
        self.logger.info(
            f"Fetching info for collection: '{collection_name}'"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist"
            )
            return {}

        try:
            col = await self.client.get_collection(collection_name)
            info = {
                "status": col.status.value if col.status else None,
                "vectors_count": col.vectors_count,
                "points_count": col.points_count,
                "config": col.config.dict() if col.config else None,
            }
            self.logger.info(f"Collection '{collection_name}' info: {info}")
            self.logger.success(
                f"Collection info retrieved for '{collection_name}'"
            )
            return info
        except Exception as e:
            self.logger.error(
                f"Error getting collection info for '{collection_name}': {e}"
            )
            return {}

    # ------------------------------------------------------------------
    # CRUD — Insert
    # ------------------------------------------------------------------

    async def insert(
        self,
        collection_name: str,
        document: VectorDocument,
    ) -> bool:
        self.logger.info(f"Inserting document into '{collection_name}'")

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist — insert aborted"
            )
            return False

        try:
            point_id = document.id if document.id is not None else str(uuid.uuid4())

            point = PointStruct(
                id=point_id,
                vector=document.vector,
                payload={
                    "content": document.content,
                    **document.payload,
                },
            )

            await self.client.upsert(
                collection_name=collection_name,
                points=[point],
            )

            self.logger.info(
                f"Document '{point_id}' inserted into '{collection_name}'"
            )
            self.logger.success(f"Insert successful — document '{point_id}'")
            return True
        except Exception as e:
            self.logger.error(f"Error inserting document: {e}")
            return False

    async def insert_many(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        batch_size: int = 100,
    ) -> bool:
        self.logger.info(
            f"Inserting {len(documents)} documents into '{collection_name}' "
            f"(batch_size={batch_size})"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist — bulk insert aborted"
            )
            return False

        if not documents:
            self.logger.warning("Empty document list — nothing to insert")
            return False

        try:
            points = [
                PointStruct(
                    id=doc.id if doc.id is not None else str(uuid.uuid4()),
                    vector=doc.vector,
                    payload={
                        "content": doc.content,
                        **doc.payload,
                    },
                )
                for doc in documents
            ]

            total_inserted = 0
            total_batches = (len(points) + batch_size - 1) // batch_size

            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                batch_num = (i // batch_size) + 1

                await self.client.upsert(
                    collection_name=collection_name,
                    points=batch,
                )

                total_inserted += len(batch)
                self.logger.info(
                    f"Batch {batch_num}/{total_batches} — "
                    f"inserted {total_inserted}/{len(points)} documents"
                )

            self.logger.success(
                f"Bulk insert complete — "
                f"{total_inserted} documents into '{collection_name}'"
            )
            return True
        except Exception as e:
            self.logger.error(f"Error during bulk insert: {e}")
            return False

    # ------------------------------------------------------------------
    # Retrieval — Single by ID
    # ------------------------------------------------------------------

    async def get_document(
        self,
        collection_name: str,
        document_id: str,
        schema: bool = True,
    ) -> VectorDocument | None:
        self.logger.info(
            f"Fetching document '{document_id}' from '{collection_name}'"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist"
            )
            return None

        try:
            results = await self.client.retrieve(
                collection_name=collection_name,
                ids=[document_id],
                with_vectors=True,
                with_payload=True,
            )

            if not results:
                self.logger.warning(
                    f"Document '{document_id}' not found in '{collection_name}'"
                )
                return None

            point = results[0]

            self.logger.info(
                f"Document '{document_id}' retrieved from '{collection_name}'"
            )

            if not schema:
                self.logger.success(
                    f"Returning raw document '{document_id}'"
                )
                return point

            doc = self._point_to_document(point)

            self.logger.success(
                f"Document '{document_id}' fetched successfully"
            )
            return doc
        except Exception as e:
            self.logger.error(
                f"Error fetching document '{document_id}': {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Retrieval — Multiple by IDs
    # ------------------------------------------------------------------

    async def get_many_documents(
        self,
        collection_name: str,
        document_ids: List[str],
        schema: bool = True,
    ) -> List[VectorDocument] | List:
        self.logger.info(
            f"Fetching {len(document_ids)} documents from '{collection_name}'"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist"
            )
            return []

        if not document_ids:
            self.logger.warning("Empty ID list — nothing to fetch")
            return []

        try:
            results = await self.client.retrieve(
                collection_name=collection_name,
                ids=document_ids,
                with_vectors=True,
                with_payload=True,
            )

            self.logger.info(
                f"Retrieved {len(results)}/{len(document_ids)} documents "
                f"from '{collection_name}'"
            )

            if not schema:
                self.logger.success(
                    f"Returning {len(results)} raw documents"
                )
                return results

            documents = [
                self._point_to_document(point) for point in results
            ]

            self.logger.success(
                f"Fetched {len(documents)} documents from '{collection_name}'"
            )
            return documents
        except Exception as e:
            self.logger.error(f"Error fetching multiple documents: {e}")
            return []

    # ------------------------------------------------------------------
    # Retrieval — All documents (with optional filter)
    # ------------------------------------------------------------------

    async def get_all_documents(
        self,
        collection_name: str,
        filters: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
        schema: bool = True,
    ) -> List[VectorDocument] | List:
        filter_msg = f"filters={filters}" if filters else "no filters"
        self.logger.info(
            f"Fetching documents from '{collection_name}' — "
            f"{filter_msg}, batch_size={batch_size}, schema={schema}"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist"
            )
            return []

        try:
            qdrant_filter = self._build_filter(filters) if filters else None

            all_points = []
            offset = None

            while True:
                results, next_offset = await self.client.scroll(
                    collection_name=collection_name,
                    scroll_filter=qdrant_filter,
                    limit=batch_size,
                    offset=offset,
                    with_vectors=True,
                    with_payload=True,
                )

                if not results:
                    break

                all_points.extend(results)
                self.logger.info(
                    f"Scrolled {len(all_points)} documents so far "
                    f"from '{collection_name}'"
                )

                if next_offset is None:
                    break

                offset = next_offset

            self.logger.info(
                f"Total documents fetched: {len(all_points)} "
                f"from '{collection_name}'"
            )

            if not schema:
                self.logger.success(
                    f"Returning {len(all_points)} raw documents "
                    f"from '{collection_name}'"
                )
                return all_points

            documents = [
                self._point_to_document(point) for point in all_points
            ]

            self.logger.success(
                f"All documents fetched — "
                f"{len(documents)} documents from '{collection_name}'"
            )
            return documents
        except Exception as e:
            self.logger.error(
                f"Error fetching documents from '{collection_name}': {e}"
            )
            return []

    # ------------------------------------------------------------------
    # Search — Vector similarity (with optional filter)
    # ------------------------------------------------------------------

    async def search(
        self,
        collection_name: str,
        vector: List[float],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
        schema: bool = True,
    ) -> List[VectorDocument] | List:
        filter_msg = f"filters={filters}" if filters else "no filters"
        self.logger.info(
            f"Searching '{collection_name}' — "
            f"top_k={top_k}, {filter_msg}, schema={schema}"
        )

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist — search aborted"
            )
            return []

        try:
            qdrant_filter = self._build_filter(filters) if filters else None

            results = await self.client.search(
                collection_name=collection_name,
                query_vector=vector,
                query_filter=qdrant_filter,
                limit=top_k,
            )

            self.logger.info(
                f"Search returned {len(results)} results "
                f"from '{collection_name}'"
            )

            if not schema:
                self.logger.success(
                    f"Returning {len(results)} raw search results "
                    f"from '{collection_name}'"
                )
                return results

            documents = [
                self._point_to_document(hit, score=hit.score)
                for hit in results
            ]

            self.logger.success(
                f"Search complete — "
                f"{len(documents)} documents from '{collection_name}'"
            )
            return documents
        except Exception as e:
            self.logger.error(f"Error searching '{collection_name}': {e}")
            return []

    # ------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------

    async def count_documents(
        self,
        collection_name: str,
    ) -> int:
        self.logger.info(f"Counting documents in '{collection_name}'")

        if not await self.collection_exists(collection_name):
            self.logger.error(
                f"Collection '{collection_name}' does not exist"
            )
            return 0

        try:
            result = await self.client.count(
                collection_name=collection_name,
            )

            count = result.count
            self.logger.info(
                f"Collection '{collection_name}' has {count} documents"
            )
            self.logger.success(
                f"Count complete — {count} documents in '{collection_name}'"
            )
            return count
        except Exception as e:
            self.logger.error(
                f"Error counting documents in '{collection_name}': {e}"
            )
            return 0