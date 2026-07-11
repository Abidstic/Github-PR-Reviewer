"""
Similarity Matcher
Uses vector embeddings to find similar PRs and reviewers
"""
    
import pickle
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    from sentence_transformers import SentenceTransformer
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_community.docstore.document import Document
    except ImportError:
        from langchain.embeddings import HuggingFaceEmbeddings
        from langchain.vectorstores import FAISS
        from langchain.docstore.document import Document
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False

    # Create dummy Document class when embeddings not available
    class Document:
        def __init__(self, page_content="", metadata=None):
            self.page_content = page_content
            self.metadata = metadata or {}

from src.utils import get_logger, get_config, get_data_dir

logger = get_logger(__name__)


class SimilarityMatcher:
    """Finds similar PRs using vector embeddings"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize similarity matcher

        Args:
            cache_dir: Directory to cache vector stores (defaults to
                       <DATA_DIR>/cache so the FAISS index lives on the
                       persistent volume)
        """
        if not EMBEDDINGS_AVAILABLE:
            raise ImportError(
                "Embeddings not available. Install with: "
                "pip install sentence-transformers faiss-cpu torch"
            )

        self.config = get_config()
        self.cache_dir = Path(cache_dir) if cache_dir else get_data_dir() / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize embeddings model
        model_name = self.config.get(
            'embeddings.model',
            'sentence-transformers/all-MiniLM-L6-v2'
        )
        
        logger.info(f"📦 Loading embeddings model: {model_name}")
        self.embeddings = HuggingFaceEmbeddings(model_name=model_name)
        
        self.vector_store = None
        self.documents = []
        
        logger.info("✅ Similarity matcher initialized")
    
    def create_embeddings_from_reviewer_data(
        self,
        reviewer_data: List[Dict]
    ) -> bool:
        """
        Create vector embeddings from reviewer PR data
        
        Args:
            reviewer_data: List of PR data with reviews
        
        Returns:
            Success boolean
        """
        logger.info(f"📊 Creating embeddings for {len(reviewer_data)} PRs...")
        
        documents = []
        
        for pr in reviewer_data:
            # Create text content with reviewer information
            author = pr.get('author', {}).get('username', 'Unknown') if pr.get('author') else 'Unknown'
            repo_name = pr.get('repo_name', 'Unknown Repository')
            
            # Get reviewer information
            reviews = pr.get('reviews', [])
            reviewers = []
            review_states = []
            
            for review in reviews:
                reviewers.append(review.get('reviewer_username', 'Unknown'))
                review_states.append(review.get('state', 'unknown'))
            
            # Get review comments
            review_comments = pr.get('review_comments', [])
            comment_authors = [
                comment.get('reviewer_username', 'Unknown')
                for comment in review_comments[:5]
            ]
            
            content = f"""
Repository: {repo_name}
PR #{pr.get('pr_number')}: {pr.get('title', '')}
Author: {author}
Description: {(pr.get('description') or '')[:300]}...
Labels: {', '.join(pr.get('labels', []))}
State: {pr.get('state', 'unknown')}
Files: {pr.get('changed_files_count', 0)} changed
Changes: +{pr.get('additions', 0)} -{pr.get('deletions', 0)}
Reviewers: {', '.join(reviewers)}
Review States: {', '.join(review_states)}
Comment Authors: {', '.join(comment_authors)}
"""
            
            # Create metadata
            metadata = {
                'pr_number': pr.get('pr_number'),
                'author': author,
                'state': pr.get('state'),
                'title': pr.get('title', ''),
                'repo_name': repo_name,
                'reviewers': reviewers,
                'review_count': len(reviews),
                'comment_count': len(review_comments)
            }
            
            # Create document
            doc = Document(page_content=content.strip(), metadata=metadata)
            documents.append(doc)
        
        # Create vector store
        logger.info("🔄 Building FAISS vector store...")
        self.vector_store = FAISS.from_documents(documents, self.embeddings)
        self.documents = documents
        
        logger.info(f"✅ Created {len(documents)} vector embeddings")
        return True
    
    def save_vector_store(self, filename: str = "reviewer_vectors.faiss"):
        """
        Save vector store to disk
        
        Args:
            filename: Filename for vector store
        """
        if not self.vector_store:
            logger.warning("⚠️ No vector store to save")
            return
        
        filepath = self.cache_dir / filename
        
        try:
            self.vector_store.save_local(str(filepath))
            logger.info(f"💾 Saved vector store to {filepath}")
        except Exception as e:
            logger.error(f"❌ Failed to save vector store: {e}")
    
    def load_vector_store(self, filename: str = "reviewer_vectors.faiss") -> bool:
        """
        Load vector store from disk
        
        Args:
            filename: Filename of saved vector store
        
        Returns:
            Success boolean
        """
        filepath = self.cache_dir / filename
        
        if not filepath.exists():
            logger.warning(f"⚠️ Vector store not found: {filepath}")
            return False
        
        try:
            self.vector_store = FAISS.load_local(
                str(filepath),
                self.embeddings,
                allow_dangerous_deserialization=True
            )
            logger.info(f"📂 Loaded vector store from {filepath}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load vector store: {e}")
            return False
    
    def find_similar_prs(
        self,
        query: str,
        k: int = 5
    ) -> List[Tuple[Document, float]]:
        """
        Find similar PRs using vector search
        
        Args:
            query: Query text (PR description, requirements, etc.)
            k: Number of similar PRs to return
        
        Returns:
            List of (document, similarity_score) tuples
        """
        if not self.vector_store:
            logger.error("❌ Vector store not initialized")
            return []
        
        try:
            # Perform similarity search with scores
            results = self.vector_store.similarity_search_with_score(query, k=k)
            
            logger.debug(f"🔍 Found {len(results)} similar PRs")
            return results
            
        except Exception as e:
            logger.error(f"❌ Similarity search failed: {e}")
            return []
    
    def extract_reviewers_from_similar_prs(
        self,
        similar_prs: List[Tuple[Document, float]]
    ) -> Dict[str, float]:
        """
        Extract reviewer suggestions from similar PRs
        
        Args:
            similar_prs: List of (document, score) tuples
        
        Returns:
            Dictionary of {reviewer_name: aggregated_score}
        """
        reviewer_scores = {}

        for doc, distance in similar_prs:
            reviewers = doc.metadata.get('reviewers', [])

            # FAISS returns L2 *distance* (lower = more similar), so we must
            # convert it to a similarity weight before accumulating. Summing the
            # raw distance would reward reviewers on the LEAST similar PRs.
            similarity_weight = 1.0 / (1.0 + distance)
            for reviewer in reviewers:
                if reviewer in reviewer_scores:
                    reviewer_scores[reviewer] += similarity_weight
                else:
                    reviewer_scores[reviewer] = similarity_weight
        
        # Sort by score
        sorted_reviewers = dict(
            sorted(reviewer_scores.items(), key=lambda x: x[1], reverse=True)
        )
        
        return sorted_reviewers


# Example usage and testing
if __name__ == "__main__":
    print("🔍 Testing Similarity Matcher")
    print("=" * 60)
    
    try:
        # Initialize matcher
        matcher = SimilarityMatcher()
        
        # Sample PR data
        sample_prs = [
            {
                'pr_number': 1,
                'title': 'Fix Express.js routing bug',
                'repo_name': 'moment',
                'author': {'username': 'developer1'},
                'description': 'Fixed routing issue in Express middleware',
                'labels': ['bug', 'backend'],
                'state': 'closed',
                'additions': 50,
                'deletions': 10,
                'changed_files_count': 3,
                'reviews': [
                    {'reviewer_username': 'reviewer1', 'state': 'APPROVED'},
                    {'reviewer_username': 'reviewer2', 'state': 'APPROVED'}
                ],
                'review_comments': []
            },
            {
                'pr_number': 2,
                'title': 'Add moment.js locale support',
                'repo_name': 'moment',
                'author': {'username': 'developer2'},
                'description': 'Added French locale support',
                'labels': ['enhancement', 'i18n'],
                'state': 'closed',
                'additions': 100,
                'deletions': 20,
                'changed_files_count': 5,
                'reviews': [
                    {'reviewer_username': 'reviewer1', 'state': 'APPROVED'}
                ],
                'review_comments': []
            }
        ]
        
        # Create embeddings
        print("\n📊 Creating embeddings...")
        success = matcher.create_embeddings_from_reviewer_data(sample_prs)
        if success:
            print("✅ Embeddings created")
        
        # Test similarity search
        print("\n🔍 Testing similarity search...")
        query = "Fix routing issue in backend"
        similar = matcher.find_similar_prs(query, k=2)
        
        print(f"✅ Found {len(similar)} similar PRs")
        for doc, score in similar:
            print(f"   PR #{doc.metadata['pr_number']}: {doc.metadata['title']} (score: {score:.3f})")
        
        # Extract reviewers
        print("\n👥 Extracting reviewer suggestions...")
        reviewers = matcher.extract_reviewers_from_similar_prs(similar)
        print(f"✅ Suggested reviewers:")
        for name, score in list(reviewers.items())[:3]:
            print(f"   - {name}: {score:.3f}")
        
        print("\n✅ Similarity matcher working correctly!")
        
    except ImportError as e:
        print(f"❌ Missing dependencies: {e}")
        print("Install with: pip install sentence-transformers faiss-cpu torch")