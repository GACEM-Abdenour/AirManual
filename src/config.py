"""Configuration module for loading environment variables."""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # OpenAI API Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Unstructured API Configuration
    UNSTRUCTURED_API_KEY: str = os.getenv("UNSTRUCTURED_API_KEY", "")
    UNSTRUCTURED_API_URL: str = os.getenv("UNSTRUCTURED_API_URL", "https://api.unstructured.io")
    
    # Qdrant: optional URL for remote (Docker/Cloud). If unset, uses local ./qdrant_db.
    # Use remote for large collections (Qdrant warns local mode >20k points).
    QDRANT_URL: str = os.getenv("QDRANT_URL", "").strip()
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "").strip()

    # Persistent OpenAI usage log (tokens + cost). Default: data/usage.json.
    # On Render, set to a path on a persistent disk if you want totals to survive deploys.
    USAGE_FILE: str = os.getenv("USAGE_FILE", "").strip() or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "usage.json"
    )
    
    @classmethod
    def validate(cls) -> None:
        """Validate that required configuration values are set."""
        missing = []
        
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not cls.UNSTRUCTURED_API_KEY:
            missing.append("UNSTRUCTURED_API_KEY")
        
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Please check your .env file or environment variables."
            )
