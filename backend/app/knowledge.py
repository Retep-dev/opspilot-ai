"""Tenant-scoped, versioned knowledge ingestion."""

import hashlib
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from pydantic import BaseModel, Field


class PassageEmbedder(Protocol):
    async def embed_passage(self, text: str) -> list[float]: ...


class KnowledgeInput(BaseModel):
    source: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=100_000)
    ingestion_version: int = Field(ge=1)


def chunk_text(content: str, size: int = 1200, overlap: int = 150) -> list[str]:
    if size <= overlap or overlap < 0:
        raise ValueError("Chunk size must exceed overlap")
    chunks = []
    step = size - overlap
    for start in range(0, len(content), step):
        chunk = content[start : start + size]
        if chunk:
            chunks.append(chunk)
        if start + size >= len(content):
            break
    return chunks


class KnowledgeIngestor:
    def __init__(self, database_url: str, embeddings: PassageEmbedder) -> None:
        self.database_url = database_url
        self.embeddings = embeddings

    async def ingest(self, tenant_id: UUID, document: KnowledgeInput) -> UUID:
        checksum = hashlib.sha256(document.content.encode()).hexdigest()
        chunks = chunk_text(document.content)
        vectors = [await self.embeddings.embed_passage(chunk) for chunk in chunks]
        if any(len(vector) != 1024 for vector in vectors):
            raise ValueError("Embedding adapter must return 1024 dimensions")
        document_id = uuid4()
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """SELECT id, checksum FROM knowledge_documents
                       WHERE tenant_id = %s AND source = %s AND ingestion_version = %s
                       FOR UPDATE""",
                    (tenant_id, document.source, document.ingestion_version),
                )
                existing = await cursor.fetchone()
                if existing:
                    if existing[1] != checksum:
                        raise ValueError(
                            "Source version already contains different content"
                        )
                    return existing[0]
                await conn.execute(
                    """INSERT INTO knowledge_documents
                       (id, tenant_id, source, access_scope, checksum, ingestion_version)
                       VALUES (%s, %s, %s, 'operations', %s, %s)""",
                    (
                        document_id,
                        tenant_id,
                        document.source,
                        checksum,
                        document.ingestion_version,
                    ),
                )
                for index, (chunk, vector) in enumerate(
                    zip(chunks, vectors, strict=True)
                ):
                    value = "[" + ",".join(str(number) for number in vector) + "]"
                    await conn.execute(
                        """INSERT INTO knowledge_chunks
                           (document_id, chunk_index, content, embedding)
                           VALUES (%s, %s, %s, %s::vector)""",
                        (document_id, index, chunk, value),
                    )
        return document_id
