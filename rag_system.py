import weaviate
import weaviate.classes as wvc
import os
import re
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

class RAGSystem:
    def __init__(self, weaviate_url: str = "http://localhost:8080"):
        """Initialize the RAG system with Weaviate client"""
        self.client = weaviate.connect_to_local(
            host="localhost",
            port=8080,
            grpc_port=50051,
            skip_init_checks=True  # Skip gRPC health checks
        )
        
        # Define the schema for our document collection
        self.schema = {
            "class": "Document",
            "description": "A class to store company documents with access control",
            "vectorizer": "text2vec-transformers",
            "moduleConfig": {
                "text2vec-transformers": {
                    "model": "sentence-transformers-multi-qa-MiniLM-L6-cos-v1",
                    "options": {
                        "waitForModel": True,
                        "useGPU": False
                    }
                }
            },
            "properties": [
                {
                    "name": "content",
                    "dataType": ["text"],
                    "description": "The actual content of the document chunk",
                    "moduleConfig": {
                        "text2vec-transformers": {
                            "skip": False,
                            "vectorizePropertyName": False
                        }
                    }
                },
                {
                    "name": "filename",
                    "dataType": ["string"],
                    "description": "Name of the source file",
                    "moduleConfig": {
                        "text2vec-transformers": {
                            "skip": True
                        }
                    }
                },
                {
                    "name": "access_level",
                    "dataType": ["string"],
                    "description": "Access level: 'user' or 'admin'",
                    "moduleConfig": {
                        "text2vec-transformers": {
                            "skip": True
                        }
                    }
                },
                {
                    "name": "chunk_id",
                    "dataType": ["int"],
                    "description": "Chunk number within the document",
                    "moduleConfig": {
                        "text2vec-transformers": {
                            "skip": True
                        }
                    }
                },
                {
                    "name": "document_type",
                    "dataType": ["string"],
                    "description": "Type of document (benefits, handbook, policy, etc.)",
                    "moduleConfig": {
                        "text2vec-transformers": {
                            "skip": True
                        }
                    }
                }
            ]
        }
        
        self.initialize_schema()
    
    def initialize_schema(self):
        """Initialize the Weaviate schema"""
        try:
            # Check if collection already exists
            if self.client.collections.exists("Document"):
                print("Document collection already exists. Deleting and recreating...")
                self.client.collections.delete("Document")
            
            # Create the collection using v4 syntax
            self.client.collections.create(
                name="Document",
                vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_transformers(),
                properties=[
                    wvc.config.Property(name="content", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="filename", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="access_level", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="chunk_id", data_type=wvc.config.DataType.INT),
                    wvc.config.Property(name="document_type", data_type=wvc.config.DataType.TEXT),
                ]
            )
            print("Document collection created successfully!")
            
        except Exception as e:
            print(f"Error initializing schema: {e}")
    
    def parse_document_content(self, content: str, filename: str) -> List[Dict[str, Any]]:
        """Parse document content and extract access-controlled sections"""
        documents = []
        
        # Split content by access level markers
        sections = re.split(r'=== ACCESS: (user|admin) ===', content)
        
        if len(sections) == 1:
            # No access markers found, default to user access
            return self._chunk_content(sections[0].strip(), filename, "user")
        
        current_access = "user"  # Default access level
        
        for i in range(1, len(sections), 2):
            if i < len(sections):
                access_level = sections[i].strip()
                if i + 1 < len(sections):
                    section_content = sections[i + 1].strip()
                    if section_content:
                        documents.extend(self._chunk_content(section_content, filename, access_level))
        
        return documents
    
    def _chunk_content(self, content: str, filename: str, access_level: str, chunk_size: int = 1000) -> List[Dict[str, Any]]:
        """Split content into chunks while preserving context"""
        chunks = []
        
        # Split by paragraphs or sections first
        paragraphs = content.split('\n\n')
        current_chunk = ""
        chunk_id = 0
        
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) < chunk_size:
                current_chunk += paragraph + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append({
                        "content": current_chunk.strip(),
                        "filename": filename,
                        "access_level": access_level,
                        "chunk_id": chunk_id,
                        "document_type": self._get_document_type(filename)
                    })
                    chunk_id += 1
                current_chunk = paragraph + "\n\n"
        
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
        documents_collection = self.client.collections.get("Document")
        
        for file_path in txt_files:
            try:
                print(f"Processing {file_path.name}...")
                
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                # Parse and chunk the document
                chunks = self.parse_document_content(content, file_path.name)
                
                # Insert chunks into Weaviate using v4 batch insert
                with documents_collection.batch.dynamic() as batch:
                    for chunk in chunks:
                        batch.add_object(
                            properties=chunk
                        )
                
                total_chunks += len(chunks)
                print(f"  - Added {len(chunks)} chunks from {file_path.name}")
                
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}")
        
        print(f"\nIngestion complete! Total chunks processed: {total_chunks}")
    
    def search(self, query: str, user_role: str = "user", limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform hybrid search (vector + keyword) with role-based access control
        
        Args:
            query: Search query
            user_role: 'user' or 'admin'
            limit: Maximum number of results to return
        """
        try:
            documents_collection = self.client.collections.get("Document")
            
            # Perform hybrid search first, then filter results
            response = documents_collection.query.hybrid(
                query=query,
                limit=limit * 2,  # Get more results to filter
                return_metadata=wvc.query.MetadataQuery(score=True)
            )
            
            # Filter results based on user role
            processed_results = []
            for item in response.objects:
                access_level = item.properties["access_level"]
                
                # Apply role-based filtering
                if user_role.lower() == "admin" or access_level == "user":
                    processed_results.append({
                        "content": item.properties["content"],
                        "filename": item.properties["filename"],
                        "access_level": item.properties["access_level"],
                        "chunk_id": item.properties["chunk_id"],
                        "document_type": item.properties["document_type"],
                        "score": item.metadata.score if item.metadata.score else 0,
                        "relevance_explanation": ""
                    })
                    
                    # Stop when we have enough results
                    if len(processed_results) >= limit:
                        break
            
            return processed_results
            
        except Exception as e:
            print(f"Error during search: {e}")
            return []
    
    def get_document_stats(self) -> Dict[str, Any]:
        """Get statistics about the ingested documents"""
        try:
            documents_collection = self.client.collections.get("Document")
            
            # Get total count
            total_response = documents_collection.aggregate.over_all(total_count=True)
            total_count = total_response.total_count
            
            # Get all documents to count by access level manually
            all_docs = documents_collection.query.fetch_objects(limit=10000)
            
            user_count = 0
            admin_count = 0
            
            for doc in all_docs.objects:
                if doc.properties["access_level"] == "user":
                    user_count += 1
                elif doc.properties["access_level"] == "admin":
                    admin_count += 1
            
            return {
                "total_chunks": total_count,
                "user_accessible_chunks": user_count,
                "admin_only_chunks": admin_count,
                "document_types": {}  # Simplified for v4
            }
            
        except Exception as e:
            print(f"Error getting document stats: {e}")
            return {}
    
    def clear_all_data(self):
        """Clear all data from the Document collection"""
        try:
            documents_collection = self.client.collections.get("Document")
            # Delete all objects in the Document collection
            documents_collection.data.delete_many(
                where=wvc.query.Filter.by_property("access_level").contains_any(["user", "admin"])
            )
            print("All document data cleared successfully!")
        except Exception as e:
            print(f"Error clearing data: {e}")
    
    def close(self):
        """Close the Weaviate client connection"""
        self.client.close()


def main():
    """Main function to demonstrate the RAG system"""
    print("🚀 Initializing RAG System with Weaviate...")
    
    # Initialize the RAG system
    rag = RAGSystem()
    
    try:
        # Ingest documents
        print("\n📚 Ingesting documents...")
        data_folder = "E:/waveaite test/data"  # Fixed Windows path
        rag.ingest_documents(data_folder)
        
        # Show statistics
        print("\n📊 Document Statistics:")
        stats = rag.get_document_stats()
        if stats:
            print(f"Total chunks: {stats['total_chunks']}")
            print(f"User-accessible chunks: {stats['user_accessible_chunks']}")
            print(f"Admin-only chunks: {stats['admin_only_chunks']}")
        
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
            
            print(f"\nFound {len(results)} relevant documents:")
            for i, result in enumerate(results, 1):
                print(f"\n--- Result {i} ---")
                print(f"Source: {result['filename']} (Chunk {result['chunk_id']})")
                print(f"Document Type: {result['document_type']}")
                print(f"Access Level: {result['access_level']}")
                print(f"Relevance Score: {result['score']:.3f}")
                print(f"Content Preview: {result['content'][:200]}...")
    
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        rag.close()


if __name__ == "__main__":
    main() 