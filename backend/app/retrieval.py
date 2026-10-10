"""Tenant-scoped pgvector retrieval; embeddings are supplied by an adapter."""

from typing import Protocol

import psycopg

from app.models import Evidence


class EmbeddingAdapter(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...


class PgVectorRetriever:
    def __init__(self, database_url: str, embeddings: EmbeddingAdapter) -> None:
        self.database_url = database_url
        self.embeddings = embeddings

    async def search(self, tenant_id: str, query: str) -> list[Evidence]:
        embedding = await self.embeddings.embed_query(query)
        if len(embedding) != 2048:
            raise ValueError("Embedding adapter must return 2048 dimensions")
        vector = "[" + ",".join(str(value) for value in embedding) + "]"
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """SELECT d.source, c.content
                       FROM knowledge_chunks c
                       JOIN knowledge_documents d ON d.id = c.document_id
                       WHERE d.tenant_id = %s AND d.access_scope = 'operations'
                       ORDER BY c.embedding <=> %s::halfvec
                       LIMIT 5""",
                    (tenant_id, vector),
                )
                rows = await cursor.fetchall()
        return [Evidence(source=source, excerpt=content) for source, content in rows]


class EmptyRetriever:
    """Explicit development fallback until an embedding provider is configured."""

    async def search(self, tenant_id: str, query: str) -> list[Evidence]:
        return []
