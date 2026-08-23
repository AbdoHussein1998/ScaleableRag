# src/DatabaseInfrastructure/Vector/Schema/vector_document.py

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class VectorDocument(BaseModel):
    id: Optional[str] = Field(
        default=None,
        description=(
            "Document ID as string. "
            "On insert: optional — if None, the provider generates one. "
            "On retrieval: always populated from the database (cast to str)."
        ),
    )
    content: str = Field(
        ...,
        description="Text content of the document",
    )
    vector: List[float] = Field(
        ...,
        description="Embedding vector",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )
    score: Optional[float] = Field(
        default=None,
        description="Similarity score — populated only on search results",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "db-generated-id-123",
                "content": "This is a sample document",
                "vector": [0.1, 0.2, 0.3],
                "payload": {"source": "web", "page": 1},
                "score": 0.95,
            }
        }