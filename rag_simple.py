import weaviate
import weaviate.classes as wvc
import os
import re
from typing import List, Dict, Any
from pathlib import Path
import time

class SimpleRAGSystem:
    def __init__(self):
        """Initialize the RAG system with Weaviate client"""
        print("Connecting to Weaviate...")
        self.client = weaviate.connect_to_local(
            host="localhost",
            port=8080,
            grpc_port=50051,
            skip_init_checks=True
        )
        print("Connected successfully!")
        
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
        documents_collection = self.client.collections.get("Document")
        
        for file_path in txt_files:
            try:
                print(f"Processing {file_path.name}...")
                
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                # Parse and chunk the document
                chunks = self.parse_document_content(content, file_path.name)
                print(f"  - Created {len(chunks)} chunks")
                
                # Insert chunks one by one with progress
                for i, chunk in enumerate(chunks):
                    try:
                        documents_collection.data.insert(chunk)
                        if (i + 1) % 5 == 0:  # Progress every 5 chunks
                            print(f"    - Inserted {i + 1}/{len(chunks)} chunks")
                    except Exception as e:
                        print(f"    - Error inserting chunk {i}: {e}")
                
                total_chunks += len(chunks)
                print(f"  - Completed {file_path.name}")
                
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}")
        
        print(f"\nIngestion complete! Total chunks processed: {total_chunks}")
    
    def search(self, query: str, user_role: str = "user", limit: int = 3) -> List[Dict[str, Any]]:
        """Perform search with role-based access control"""
        try:
            documents_collection = self.client.collections.get("Document")
            
            # Simple vector search first
            response = documents_collection.query.near_text(
                query=query,
                limit=limit * 3,  # Get more to filter
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
                        "score": item.metadata.score if item.metadata.score else 0
                    })
                    
                    if len(processed_results) >= limit:
                        break
            
            return processed_results
            
        except Exception as e:
            print(f"Error during search: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get simple statistics"""
        try:
            documents_collection = self.client.collections.get("Document")
            total_response = documents_collection.aggregate.over_all(total_count=True)
            return {"total_chunks": total_response.total_count}
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {"total_chunks": 0}
    
    def close(self):
        """Close the Weaviate client connection"""
        self.client.close()


def main():
    """Main function to demonstrate the RAG system"""
    print("🚀 Starting Simple RAG System...")
    
    rag = SimpleRAGSystem()
    
    try:
        # Ingest documents
        print("\n📚 Ingesting documents...")
        data_folder = "E:/waveaite test/data"
        rag.ingest_documents(data_folder)
        
        # Show statistics
        print("\n📊 Statistics:")
        stats = rag.get_stats()
        print(f"Total chunks: {stats['total_chunks']}")
        
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