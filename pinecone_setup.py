import os
import time
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
from typing import List, Dict
import hashlib

class AfricaCreativeRAG:
    def __init__(self, api_key: str, index_name: str = "africa-creative-economy"):
        """Initialize Pinecone and embedding model"""
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.dimension = 384
        
        # Create index if it doesn't exist
        if index_name not in self.pc.list_indexes().names():
            self.pc.create_index(
                name=index_name,
                dimension=self.dimension,
                metric='cosine',
                spec=ServerlessSpec(cloud='aws', region='us-east-1')
            )
            time.sleep(1)
        
        self.index = self.pc.Index(index_name)
        self.visited_urls = set()
    
    def scrape_article(self, url: str) -> Dict:
        """Scrape article content from URL"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = soup.find('h1')
            title_text = title.get_text().strip() if title else "No Title"
            
            # Extract article content
            article_content = []
            
            # Try common article containers
            article = soup.find('article') or soup.find('div', class_=re.compile('content|article|post'))
            
            if article:
                paragraphs = article.find_all(['p', 'h2', 'h3'])
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 50:  # Filter out short snippets
                        article_content.append(text)
            
            content = ' '.join(article_content) if article_content else ""
            
            return {
                'url': url,
                'title': title_text,
                'content': content,
                'success': len(content) > 100
            }
        except Exception as e:
            print(f"Error scraping {url}: {str(e)}")
            return {'url': url, 'title': '', 'content': '', 'success': False}
    
    def find_article_links(self, base_url: str, max_pages: int = 50) -> List[str]:
        """Find all article links from the website"""
        links = set()
        to_visit = [base_url]
        
        while to_visit and len(links) < max_pages:
            current_url = to_visit.pop(0)
            
            if current_url in self.visited_urls:
                continue
            
            self.visited_urls.add(current_url)
            
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(current_url, headers=headers, timeout=10)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find all links
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urljoin(base_url, href)
                    
                    # Only include links from the same domain
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        # Filter for article-like URLs
                        if any(pattern in full_url for pattern in ['/20', 'article', 'post', 'blog']):
                            links.add(full_url)
                
                print(f"Found {len(links)} article links so far...")
                time.sleep(1)  # Be respectful with scraping
                
            except Exception as e:
                print(f"Error finding links on {current_url}: {str(e)}")
        
        return list(links)
    
    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), chunk_size - overlap):
            chunk = ' '.join(words[i:i + chunk_size])
            if len(chunk) > 100:  # Minimum chunk size
                chunks.append(chunk)
        
        return chunks
    
    def generate_id(self, text: str) -> str:
        """Generate unique ID for text chunk"""
        return hashlib.md5(text.encode()).hexdigest()
    
    def index_articles(self, base_url: str, max_articles: int = 50):
        """Scrape and index articles from the website"""
        print(f"Finding article links from {base_url}...")
        article_urls = self.find_article_links(base_url, max_articles)
        
        print(f"\nFound {len(article_urls)} articles. Starting indexing...")
        
        vectors_to_upsert = []
        batch_size = 100
        
        for idx, url in enumerate(article_urls):
            print(f"Processing article {idx+1}/{len(article_urls)}: {url}")
            
            article_data = self.scrape_article(url)
            
            if not article_data['success']:
                continue
            
            # Chunk the content
            chunks = self.chunk_text(article_data['content'])
            
            for chunk_idx, chunk in enumerate(chunks):
                # Generate embedding
                embedding = self.embedding_model.encode(chunk).tolist()
                
                # Create metadata
                metadata = {
                    'text': chunk,
                    'title': article_data['title'],
                    'url': url,
                    'chunk_index': chunk_idx
                }
                
                # Create unique ID
                vector_id = f"{self.generate_id(url)}_{chunk_idx}"
                
                vectors_to_upsert.append({
                    'id': vector_id,
                    'values': embedding,
                    'metadata': metadata
                })
                
                # Upsert in batches
                if len(vectors_to_upsert) >= batch_size:
                    self.index.upsert(vectors=vectors_to_upsert)
                    print(f"  Upserted batch of {len(vectors_to_upsert)} vectors")
                    vectors_to_upsert = []
            
            time.sleep(0.5)  # Rate limiting
        
        # Upsert remaining vectors
        if vectors_to_upsert:
            self.index.upsert(vectors=vectors_to_upsert)
            print(f"Upserted final batch of {len(vectors_to_upsert)} vectors")
        
        print(f"\n✓ Indexing complete! Total vectors in index: {self.index.describe_index_stats()}")
    
    def query(self, query_text: str, top_k: int = 5) -> List[Dict]:
        """Query the vector database"""
        query_embedding = self.embedding_model.encode(query_text).tolist()
        
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )
        
        return [
            {
                'text': match['metadata']['text'],
                'title': match['metadata']['title'],
                'url': match['metadata']['url'],
                'score': match['score']
            }
            for match in results['matches']
        ]


# Example usage
if __name__ == "__main__":
    # Set your Pinecone API key
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "your-api-key-here")
    
    # Initialize
    rag = AfricaCreativeRAG(api_key=PINECONE_API_KEY)
    
    # Index articles (run this once to populate the database)
    # rag.index_articles("https://readcommunique.com", max_articles=50)
    
    # Query example
    results = rag.query("What are the trends in African music industry?")
    for i, result in enumerate(results):
        print(f"\n{i+1}. {result['title']}")
        print(f"Score: {result['score']:.3f}")
        print(f"Text: {result['text'][:200]}...")
        print(f"URL: {result['url']}")
