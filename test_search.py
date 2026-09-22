"""
test_search.py
Performs a vector search against the Azure AI Search index created by
index_docs.py and prints the top-3 results.

Run:
    python test_search.py

Required .env variables (same as index_docs.py):
    AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_KEY, AZURE_EMBEDDING_DEPLOYMENT,
    AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX
"""

import os
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

load_dotenv()

FOUNDRY_ENDPOINT = os.environ["AZURE_FOUNDRY_ENDPOINT"].rstrip("/")
FOUNDRY_KEY      = os.environ["AZURE_FOUNDRY_KEY"]
EMBED_DEPLOYMENT = os.environ["AZURE_EMBEDDING_DEPLOYMENT"]
SEARCH_ENDPOINT  = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY       = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME       = os.environ["AZURE_SEARCH_INDEX"]

QUERY            = "maintenance interval"
TOP_K            = 3


def get_embedding(client: AzureOpenAI, text: str) -> list[float]:
    response = client.embeddings.create(
        model=EMBED_DEPLOYMENT,
        input=[text],
    )
    return response.data[0].embedding


def main():
    print(f'\n🔍  Vector search: "{QUERY}"  (top {TOP_K})\n')

    # Embed the query
    openai_client = AzureOpenAI(
        azure_endpoint=FOUNDRY_ENDPOINT,
        api_key=FOUNDRY_KEY,
        api_version="2024-10-21",
    )
    query_vector = get_embedding(openai_client, QUERY)
    print(f"  Query embedded ({len(query_vector)} dimensions).\n")

    # Vector search
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY),
    )

    vector_query = VectorizedQuery(
        vector=query_vector,
        k_nearest_neighbors=TOP_K,
        fields="embedding",          # the vector field name in the index
    )

    results = search_client.search(
        search_text=None,            # pure vector search (no keyword component)
        vector_queries=[vector_query],
        select=["id", "content", "source_file"],
        top=TOP_K,
    )

    SEP = "─" * 70
    found = 0
    for rank, result in enumerate(results, start=1):
        found += 1
        score   = result.get("@search.score", "n/a")
        source  = result.get("source_file", "unknown")
        content = result.get("content", "")
        # Show first 300 characters of the chunk
        preview = content[:300].replace("\n", " ")
        if len(content) > 300:
            preview += "…"

        print(SEP)
        print(f"  Result #{rank}")
        print(f"  Source file : {source}")
        print(f"  Score       : {score:.6f}" if isinstance(score, float) else f"  Score: {score}")
        print(f"  Preview     : {preview}")

    print(SEP)
    if found == 0:
        print("  ⚠️  No results returned. Check that index_docs.py ran successfully.")
    else:
        print(f"\n✅  {found} result(s) returned.")


if __name__ == "__main__":
    main()
