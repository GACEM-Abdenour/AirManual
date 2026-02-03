"""Index storage module using Qdrant. Cloud = Dense-Only, Local = Hybrid search."""
import os
import warnings
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.query_engine import RetrieverQueryEngine

if TYPE_CHECKING:
    from llama_index.core.retrievers import BaseRetriever
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from src.config import Config


# Global index instance
_index: Optional[VectorStoreIndex] = None

# Qdrant collection name
COLLECTION_NAME = "aircraft_maintenance_docs"

# Path for local Qdrant storage (used only when QDRANT_URL is not set)
QDRANT_PATH = Path("./qdrant_db")


def _use_hybrid_search() -> bool:
    """Cloud is Dense-Only; Local has sparse vectors -> Hybrid."""
    return not bool(Config.QDRANT_URL)


def get_qdrant_client() -> QdrantClient:
    """Initialize and return a Qdrant client (remote if QDRANT_URL set, else local).
    
    For large collections (20k+ points), set QDRANT_URL and QDRANT_API_KEY
    to use Qdrant Cloud for better performance.
    
    Returns:
        QdrantClient instance
    """
    if Config.QDRANT_URL:
        # Use Qdrant Cloud or remote server
        return QdrantClient(
            url=Config.QDRANT_URL,
            api_key=Config.QDRANT_API_KEY if Config.QDRANT_API_KEY else None,
        )
    QDRANT_PATH.mkdir(exist_ok=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*not recommended for collections.*")
        client = QdrantClient(path=str(QDRANT_PATH))
    return client


def get_embedding_model() -> BaseEmbedding:
    """Get the OpenAI embedding model.
    
    Returns:
        OpenAIEmbedding instance
    """
    return OpenAIEmbedding(
        model="text-embedding-3-small",
        api_key=Config.OPENAI_API_KEY,
    )


def create_vector_store(collection_name: str = COLLECTION_NAME) -> QdrantVectorStore:
    """Create a Qdrant vector store. Cloud = Dense-Only, Local = Hybrid.
    
    Args:
        collection_name: Name of the Qdrant collection
        
    Returns:
        QdrantVectorStore instance
    """
    client = get_qdrant_client()
    use_hybrid = _use_hybrid_search()
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        enable_hybrid=use_hybrid,
    )
    return vector_store


def create_index(
    documents: List[Document],
    reset: bool = False,
) -> VectorStoreIndex:
    """Create a VectorStoreIndex with Qdrant.
    
    Args:
        documents: List of documents to index
        reset: If True, reset the collection before indexing
        
    Returns:
        VectorStoreIndex instance
    """
    global _index
    
    # Validate configuration
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for indexing")
    
    # Get embedding model
    embed_model = get_embedding_model()
    
    client = get_qdrant_client()
    
    # Reset collection if requested (required when switching dense-only <-> hybrid)
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"Deleted existing collection: {COLLECTION_NAME}")
        except Exception as e:
            print(f"Error deleting collection (may not exist): {e}")

    use_hybrid = _use_hybrid_search()
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        enable_hybrid=use_hybrid,
    )
    
    # Create storage context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    
    # Create index from documents
    print(f"Creating index with {len(documents)} documents...")
    _index = VectorStoreIndex.from_documents(
        documents=documents,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True,
    )
    print("Index created successfully!")
    try:
        client.close()
    except Exception:
        pass
    return _index


def get_index(
    collection_name: str = COLLECTION_NAME,
    force_reload: bool = False,
) -> VectorStoreIndex:
    """Get or create the global index instance.
    
    This function provides a singleton pattern for the index,
    allowing other scripts to reuse the same index instance.
    
    Args:
        collection_name: Name of the Qdrant collection
        force_reload: If True, reload the index even if it's already loaded
        
    Returns:
        VectorStoreIndex instance
    """
    global _index
    
    if _index is None or force_reload:
        # Load existing index from vector store
        try:
            embed_model = get_embedding_model()
            client = get_qdrant_client()
            use_hybrid = _use_hybrid_search()
            vector_store = QdrantVectorStore(
                client=client,
                collection_name=collection_name,
                enable_hybrid=use_hybrid,
            )
            _index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
                embed_model=embed_model,
            )
        except Exception as e:
            print(f"Could not load existing index: {e}")
            print("You may need to run ingestion first to create the index.")
            raise
    
    return _index


def add_documents_to_index(
    documents: List[Document],
    collection_name: str = COLLECTION_NAME,
) -> None:
    """Add new documents to an existing index.
    
    Args:
        documents: List of documents to add
        collection_name: Name of the Qdrant collection
    """
    index = get_index(collection_name=collection_name)
    
    # Get the retriever to add documents
    # We'll use the index's insert method
    for doc in documents:
        index.insert(doc)
    
    print(f"Added {len(documents)} documents to the index")


def get_query_engine():
    """Load existing index and return a query engine. Cloud = Dense-Only, Local = Hybrid.
    
    Returns:
        RetrieverQueryEngine instance
    """
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for query engine")
    
    embed_model = get_embedding_model()
    client = get_qdrant_client()
    use_hybrid = _use_hybrid_search()
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        enable_hybrid=use_hybrid,
    )
    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embed_model,
    )
    query_engine = index.as_query_engine(
        similarity_top_k=5,
        vector_store_kwargs={"enable_hybrid": use_hybrid},
    )
    return query_engine


def get_retriever(
    similarity_top_k: int = 10,
    collection_name: str = COLLECTION_NAME,
) -> "BaseRetriever":
    """Get a retriever. Cloud = Dense-Only, Local = Hybrid.
    
    Uses the same index (and thus same Qdrant client) as get_index() to avoid
    "already accessed by another instance" when using local Qdrant storage.
    
    Args:
        similarity_top_k: Number of top results to retrieve
        collection_name: Name of the Qdrant collection (must match get_index)
        
    Returns:
        Retriever instance
    """
    index = get_index(collection_name=collection_name)
    return index.as_retriever(similarity_top_k=similarity_top_k)
