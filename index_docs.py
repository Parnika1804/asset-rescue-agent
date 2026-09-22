"""
index_docs.py
Reads the 4 policy Markdown files in /docs, splits them into ~500-token
chunks with overlap, embeds each chunk with Azure OpenAI, creates (or
recreates) an Azure AI Search vector index, and uploads all chunks.

Run:
    python index_docs.py

Required .env variables:
    AZURE_FOUNDRY_ENDPOINT        – Azure OpenAI resource endpoint
    AZURE_FOUNDRY_KEY             – Azure OpenAI API key
    AZURE_EMBEDDING_DEPLOYMENT    – Embedding model deployment name
    AZURE_SEARCH_ENDPOINT         – Azure AI Search service endpoint
    AZURE_SEARCH_KEY              – Azure AI Search admin key
    AZURE_SEARCH_INDEX            – Name to use for the search index
"""

import os
import re
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
)

load_dotenv()

# ── config from .env ──────────────────────────────────────────────────────────
FOUNDRY_ENDPOINT   = os.environ["AZURE_FOUNDRY_ENDPOINT"].rstrip("/")
FOUNDRY_KEY        = os.environ["AZURE_FOUNDRY_KEY"]
EMBED_DEPLOYMENT   = os.environ["AZURE_EMBEDDING_DEPLOYMENT"]
SEARCH_ENDPOINT    = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY         = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME         = os.environ["AZURE_SEARCH_INDEX"]

DOCS_DIR           = Path("docs")

# Chunking parameters (approximate tokens; 1 token ≈ 4 characters for English)
CHUNK_CHARS        = 2000   # ~500 tokens
OVERLAP_CHARS      = 200    # ~50 tokens overlap between consecutive chunks

# Azure AI Search vector dimensions depend on the embedding model:
#   text-embedding-ada-002  → 1536
#   text-embedding-3-small  → 1536  (default; can be reduced)
#   text-embedding-3-large  → 3072
# We ask the model itself for the correct size after the first embedding.
VECTOR_DIMENSIONS  = None   # resolved dynamically below


# ── 1. Read all Markdown files ────────────────────────────────────────────────
def read_docs(docs_dir: Path) -> list[dict]:
    """Return a list of {filename, text} dicts for every .md file in docs_dir."""
    docs = []
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        docs.append({"filename": md_file.name, "text": text})
        print(f"  📄  {md_file.name}  ({len(text):,} chars)")
    return docs


# ── 2. Split into overlapping chunks ─────────────────────────────────────────
def split_into_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split text into overlapping character-based chunks.
    We prefer splitting on paragraph boundaries (double newline) to avoid
    cutting mid-sentence. If a paragraph is larger than chunk_size it is
    split at the nearest space.
    """
    # Normalise line endings
    text = text.replace("\r\n", "\n").strip()
    paragraphs = re.split(r"\n{2,}", text)

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If adding this paragraph keeps us under chunk_size, accumulate
        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            # Save the current buffer as a chunk
            if current:
                chunks.append(current)
            # If the paragraph itself is bigger than chunk_size, hard-split it
            if len(para) > chunk_size:
                words = para.split()
                buf = ""
                for word in words:
                    if len(buf) + len(word) + 1 <= chunk_size:
                        buf = (buf + " " + word).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = word
                if buf:
                    current = buf
                else:
                    current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # Add overlap: prepend the tail of the previous chunk to each chunk
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:]
            overlapped.append(tail + "\n\n" + chunks[i])
        return overlapped

    return chunks


# ── 3. Embed a list of texts ──────────────────────────────────────────────────
def embed_texts(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text strings using Azure OpenAI.
    Batches of up to 16 at a time (well within the 2,048-input and
    300,000-token limits documented by Microsoft).
    """
    all_vectors: list[list[float]] = []
    batch_size = 16

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            model=EMBED_DEPLOYMENT,
            input=batch,
        )
        # response.data is sorted by index
        for item in sorted(response.data, key=lambda x: x.index):
            all_vectors.append(item.embedding)

    return all_vectors


# ── 4. Create or recreate the Azure AI Search index ───────────────────────────
def create_index(index_client: SearchIndexClient, dimensions: int):
    """
    Creates the vector index from scratch.
    If an index with the same name already exists it is deleted first,
    so re-running index_docs.py always produces a clean index.

    Fields:
        id          (key)   – deterministic hash of source_file + chunk position
        content             – the raw chunk text (searchable)
        source_file         – original Markdown filename (filterable)
        embedding           – vector field (Collection(Edm.Single))
    """
    # Delete existing index if present
    existing = [idx.name for idx in index_client.list_indexes()]
    if INDEX_NAME in existing:
        index_client.delete_index(INDEX_NAME)
        print(f"  🗑️   Deleted existing index '{INDEX_NAME}'")

    # Vector search configuration — HNSW with cosine similarity (matches OpenAI)
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="hnsw-cosine",
                parameters={"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"},
            )
        ],
        profiles=[
            VectorSearchProfile(name="default-profile", algorithm_configuration_name="hnsw-cosine")
        ],
    )

    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
        ),
        SearchableField(
            name="content",
            type=SearchFieldDataType.String,
            retrievable=True,
        ),
        SimpleField(
            name="source_file",
            type=SearchFieldDataType.String,
            filterable=True,
            retrievable=True,
        ),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            retrievable=False,   # raw floats not needed in responses
            vector_search_dimensions=dimensions,
            vector_search_profile_name="default-profile",
        ),
    ]

    index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)
    index_client.create_index(index)
    print(f"  ✅  Created index '{INDEX_NAME}' (dimensions={dimensions})")


# ── 5. Upload documents ───────────────────────────────────────────────────────
def upload_chunks(
    search_client: SearchClient,
    chunks_with_embeddings: list[dict],
):
    """Upload all chunks in a single batch (≤ 1,000 docs per batch)."""
    batch_size = 1000
    total = len(chunks_with_embeddings)
    for i in range(0, total, batch_size):
        batch = chunks_with_embeddings[i : i + batch_size]
        result = search_client.upload_documents(documents=batch)
        succeeded = sum(1 for r in result if r.succeeded)
        print(f"  📤  Uploaded docs {i+1}–{i+len(batch)}: {succeeded}/{len(batch)} succeeded")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n═══ Step 1: Reading policy documents ═══")
    docs = read_docs(DOCS_DIR)
    if not docs:
        print("❌  No .md files found in /docs. Aborting.")
        return
    print(f"  Found {len(docs)} documents.\n")

    print("═══ Step 2: Chunking ═══")
    all_chunks: list[dict] = []   # {id, content, source_file}
    for doc in docs:
        chunks = split_into_chunks(doc["text"], CHUNK_CHARS, OVERLAP_CHARS)
        for idx, chunk in enumerate(chunks):
            # Deterministic ID: hash of filename + position
            chunk_id = hashlib.md5(f"{doc['filename']}-{idx}".encode()).hexdigest()
            all_chunks.append({
                "id":          chunk_id,
                "content":     chunk,
                "source_file": doc["filename"],
            })
        print(f"  {doc['filename']:35s} → {len(chunks)} chunks")
    print(f"  Total chunks: {len(all_chunks)}\n")

    print("═══ Step 3: Generating embeddings ═══")
    openai_client = AzureOpenAI(
        azure_endpoint=FOUNDRY_ENDPOINT,
        api_key=FOUNDRY_KEY,
        api_version="2024-10-21",
    )

    texts = [c["content"] for c in all_chunks]
    print(f"  Embedding {len(texts)} chunks via '{EMBED_DEPLOYMENT}'…")
    vectors = embed_texts(openai_client, texts)
    print(f"  ✅  Got {len(vectors)} embeddings, each {len(vectors[0])} dimensions.\n")

    # Attach embeddings to chunks
    for chunk, vector in zip(all_chunks, vectors):
        chunk["embedding"] = vector

    # Resolve vector dimensions from the actual response
    dimensions = len(vectors[0])

    print("═══ Step 4: Creating Azure AI Search index ═══")
    index_client = SearchIndexClient(
        endpoint=SEARCH_ENDPOINT,
        credential=AzureKeyCredential(SEARCH_KEY),
    )
    create_index(index_client, dimensions)
    print()

    print("═══ Step 5: Uploading chunks ═══")
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY),
    )
    upload_chunks(search_client, all_chunks)

    print(f"\n✅  Done — {len(all_chunks)} chunks indexed in '{INDEX_NAME}'.")


if __name__ == "__main__":
    main()
