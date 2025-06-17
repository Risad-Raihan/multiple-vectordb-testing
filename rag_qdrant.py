import requests
import re
import time
import uuid
from typing import List, Dict, Any
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

class QdrantRAGSystem:
    def __init__(self):
        """Initialize the RAG system with Qdrant client"""
        print("Connecting to Qdrant...")
        self.client = QdrantClient(host="localhost", port=6333)
        self.embedding_url = "http://localhost:8081"
        self.collection_name = "documents"
        
        print("Connected successfully!")
        self.initialize_collection()
    
    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings from the transformer service"""
        try:
            # Call the API for each text individually as it expects a string, not a list
            embeddings = []
            for text in texts:
                response = requests.post(
                    f"{self.embedding_url}/vectors",
                    json={"text": text}
                )
                response.raise_for_status()
                embeddings.append(response.json()["vector"])
            return embeddings
        except Exception as e:
            print(f"Error getting embeddings: {e}")
            return []
    
    def initialize_collection(self):
        """Initialize the Qdrant collection"""
        try:
            # Delete collection if it exists
            try:
                self.client.delete_collection(self.collection_name)
                print("Deleted existing collection")
            except:
                pass
            
            # Create collection with vector configuration
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)
            )
            print("Document collection created successfully!")
            
        except Exception as e:
            print(f"Error initializing collection: {e}")
    
    def parse_document_content(self, content: str, filename: str) -> List[Dict[str, Any]]:
        """Parse document content and extract access-controlled sections"""
        documents = []
        
        # Split content by access level markers
        sections = re.split(r'=== ACCESS: (user|admin) ===', content)
        
        if len(sections) == 1:
            # No access markers found, default to user access
            return self._chunk_content(sections[0].strip(), filename, "user")
        
        for i in range(1, len(sections), 2):
            if i < len(sections):
                access_level = sections[i].strip()
                if i + 1 < len(sections):
                    section_content = sections[i + 1].strip()
                    if section_content:
                        documents.extend(self._chunk_content(section_content, filename, access_level))
        
        return documents
    
    def _chunk_content(self, content: str, filename: str, access_level: str, chunk_size: int = 300) -> List[Dict[str, Any]]:
        """Split content into smaller, manageable chunks"""
        chunks = []
        
        # Split by paragraphs first
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        current_chunk = ""
        chunk_id = 0
        
        for paragraph in paragraphs:
            # If adding this paragraph would exceed chunk size, save current chunk
            if len(current_chunk) + len(paragraph) > chunk_size and current_chunk.strip():
                chunks.append({
                    "content": current_chunk.strip(),
                    "filename": filename,
                    "access_level": access_level,
                    "chunk_id": chunk_id,
                    "document_type": self._get_document_type(filename)
                })
                chunk_id += 1
                current_chunk = paragraph + "\n\n"
            else:
                current_chunk += paragraph + "\n\n"
        
        # Add the last chunk
        if current_chunk.strip():
            chunks.append({
                "content": current_chunk.strip(),
                "filename": filename,
                "access_level": access_level,
                "chunk_id": chunk_id,
                "document_type": self._get_document_type(filename)
            })
        
        return chunks
    
    def _get_document_type(self, filename: str) -> str:
        """Determine document type from filename"""
        filename_lower = filename.lower()
        if "benefits" in filename_lower:
            return "benefits"
        elif "handbook" in filename_lower:
            return "handbook"
        elif "leave" in filename_lower:
            return "leave_policy"
        elif "performance" in filename_lower:
            return "performance"
        elif "compensation" in filename_lower:
            return "compensation"
        elif "termination" in filename_lower:
            return "termination"
        else:
            return "policy"
    
    def ingest_documents(self, data_folder: str):
        """Ingest all documents from the data folder"""
        data_path = Path(data_folder)
        
        if not data_path.exists():
            print(f"Data folder {data_folder} does not exist!")
            return
        
        # Process all .txt files in the data folder
        txt_files = list(data_path.glob("*.txt"))
        
        if not txt_files:
            print("No .txt files found in the data folder!")
            return
        
        print(f"Found {len(txt_files)} text files to process...")
        
        total_chunks = 0
        start_time = time.time()
        
        for file_path in txt_files:
            try:
                print(f"Processing {file_path.name}...")
                
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                # Parse and chunk the document
                chunks = self.parse_document_content(content, file_path.name)
                print(f"  - Created {len(chunks)} chunks")
                
                # Prepare texts for embedding
                texts = [chunk["content"] for chunk in chunks]
                
                # Get embeddings in batches
                batch_size = 10
                points = []
                
                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i:i + batch_size]
                    batch_chunks = chunks[i:i + batch_size]
                    
                    embeddings = self.get_embeddings(batch_texts)
                    
                    if embeddings:
                        for j, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                            point_id = str(uuid.uuid4())
                            points.append(
                                PointStruct(
                                    id=point_id,
                                    vector=embedding,
                                    payload=chunk
                                )
                            )
                        
                        if (i + batch_size) % 20 == 0:  # Progress every 20 chunks
                            print(f"    - Processed {min(i + batch_size, len(texts))}/{len(texts)} chunks")
                
                # Insert all points for this file
                if points:
                    self.client.upsert(
                        collection_name=self.collection_name,
                        points=points
                    )
                
                total_chunks += len(chunks)
                print(f"  - Completed {file_path.name}")
                
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}")
        
        end_time = time.time()
        print(f"\nIngestion complete!")
        print(f"Total chunks processed: {total_chunks}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print(f"Speed: {total_chunks / (end_time - start_time):.2f} chunks/second")
    
    def search(self, query: str, user_role: str = "user", limit: int = 3) -> List[Dict[str, Any]]:
        """Perform search with role-based access control"""
        try:
            start_time = time.time()
            
            # Get query embedding
            query_embedding = self.get_embeddings([query])
            if not query_embedding:
                return []
            
            # Create filter based on user role
            if user_role.lower() == "admin":
                # Admin can see both user and admin content
                filter_condition = Filter(
                    should=[
                        FieldCondition(key="access_level", match=MatchValue(value="user")),
                        FieldCondition(key="access_level", match=MatchValue(value="admin"))
                    ]
                )
            else:
                # Regular users can only see user content
                filter_condition = Filter(
                    must=[
                        FieldCondition(key="access_level", match=MatchValue(value="user"))
                    ]
                )
            
            # Perform search
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding[0],
                query_filter=filter_condition,
                limit=limit,
                with_payload=True
            )
            
            end_time = time.time()
            
            # Process results
            processed_results = []
            for result in search_results:
                processed_results.append({
                    "content": result.payload["content"],
                    "filename": result.payload["filename"],
                    "access_level": result.payload["access_level"],
                    "chunk_id": result.payload["chunk_id"],
                    "document_type": result.payload["document_type"],
                    "score": result.score,
                    "search_time": end_time - start_time
                })
            
            return processed_results
            
        except Exception as e:
            print(f"Error during search: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get simple statistics"""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "total_chunks": info.points_count,
                "vector_dimension": info.config.params.vectors.size
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {"total_chunks": 0}
    
    def close(self):
        """Close the Qdrant client connection"""
        self.client.close()


def main():
    """Main function to demonstrate the RAG system"""
    print("🚀 Starting Qdrant RAG System...")
    
    rag = QdrantRAGSystem()
    
    try:
        # Ingest documents
        print("\n📚 Ingesting documents...")
        data_folder = "E:/waveaite test/data"
        rag.ingest_documents(data_folder)
        
        # Show statistics
        print("\n📊 Statistics:")
        stats = rag.get_stats()
        print(f"Total chunks: {stats['total_chunks']}")
        if 'vector_dimension' in stats:
            print(f"Vector dimension: {stats['vector_dimension']}")
        
        # Interactive search loop
        print("\n🔍 Interactive Search (type 'quit' to exit, 'switch' to change role)")
        current_role = "user"
        
        while True:
            print(f"\nCurrent role: {current_role}")
            query = input("Enter your question: ").strip()
            
            if query.lower() == 'quit':
                break
            elif query.lower() == 'switch':
                current_role = "admin" if current_role == "user" else "user"
                print(f"Switched to {current_role} role")
                continue
            elif not query:
                continue
            
            print(f"\n🔍 Searching as {current_role}...")
            results = rag.search(query, user_role=current_role, limit=3)
            
            if not results:
                print("No relevant documents found.")
                continue
            
            search_time = results[0].get('search_time', 0) if results else 0
            print(f"Search completed in {search_time:.3f} seconds")
            print(f"\nFound {len(results)} relevant documents:")
            
            for i, result in enumerate(results, 1):
                print(f"\n--- Result {i} ---")
                print(f"Source: {result['filename']} (Chunk {result['chunk_id']})")
                print(f"Document Type: {result['document_type']}")
                print(f"Access Level: {result['access_level']}")
                print(f"Score: {result['score']:.3f}")
                print(f"Content: {result['content'][:200]}...")
    
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        rag.close()


if __name__ == "__main__":
    main() 