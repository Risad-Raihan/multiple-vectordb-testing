"""
Vector Database Comparison: Qdrant vs Weaviate
This script compares search performance and results quality between the two systems.
"""

import time
import statistics
from typing import List, Dict, Any

# Import both RAG systems
import sys
import os
sys.path.append(os.path.dirname(__file__))

from rag_qdrant import QdrantRAGSystem
from rag_simple import SimpleRAGSystem

def benchmark_search(rag_system, system_name: str, queries: List[str], user_role: str = "user") -> Dict[str, Any]:
    """Benchmark search performance for a RAG system"""
    print(f"\n🔍 Testing {system_name} as {user_role}...")
    
    results = {
        "system": system_name,
        "role": user_role,
        "query_times": [],
        "total_results": 0,
        "avg_scores": [],
        "all_results": []
    }
    
    for i, query in enumerate(queries, 1):
        print(f"  Query {i}/{len(queries)}: {query[:50]}...")
        
        start_time = time.time()
        search_results = rag_system.search(query, user_role=user_role, limit=3)
        end_time = time.time()
        
        query_time = end_time - start_time
        results["query_times"].append(query_time)
        results["total_results"] += len(search_results)
        
        if search_results:
            avg_score = sum(r.get('score', 0) for r in search_results) / len(search_results)
            results["avg_scores"].append(avg_score)
            results["all_results"].append({
                "query": query,
                "results": search_results,
                "time": query_time
            })
        
        print(f"    - Time: {query_time:.3f}s, Results: {len(search_results)}")
    
    # Calculate statistics
    results["avg_query_time"] = statistics.mean(results["query_times"])
    results["min_query_time"] = min(results["query_times"])
    results["max_query_time"] = max(results["query_times"])
    results["avg_result_score"] = statistics.mean(results["avg_scores"]) if results["avg_scores"] else 0
    
    return results

def compare_systems():
    """Compare Qdrant and Weaviate systems"""
    print("🚀 Vector Database Comparison: Qdrant vs Weaviate")
    print("=" * 60)
    
    # Test queries - mix of user and admin content
    test_queries = [
        "What are the health insurance benefits?",
        "How much vacation time do I get?",
        "What is the salary range for senior engineers?",  # Admin content
        "How do I request time off?",
        "What happens during performance reviews?",
        "Tell me about company policies",
        "What are the termination procedures?",  # Admin content
        "How do I enroll in benefits?"
    ]
    
    systems_to_test = []
    
    # Initialize Qdrant
    try:
        print("\n📊 Initializing Qdrant system...")
        qdrant_rag = QdrantRAGSystem()
        qdrant_stats = qdrant_rag.get_stats()
        print(f"Qdrant ready - Total chunks: {qdrant_stats.get('total_chunks', 0)}")
        systems_to_test.append(("Qdrant", qdrant_rag))
    except Exception as e:
        print(f"❌ Failed to initialize Qdrant: {e}")
    
    # Initialize Weaviate
    try:
        print("\n📊 Initializing Weaviate system...")
        weaviate_rag = SimpleRAGSystem()
        weaviate_stats = weaviate_rag.get_stats()
        print(f"Weaviate ready - Total chunks: {weaviate_stats.get('total_chunks', 0)}")
        systems_to_test.append(("Weaviate", weaviate_rag))
    except Exception as e:
        print(f"❌ Failed to initialize Weaviate: {e}")
    
    if len(systems_to_test) < 2:
        print("❌ Need both systems running for comparison")
        return
    
    print(f"\n🎯 Running {len(test_queries)} test queries on both systems...")
    print("Testing both USER and ADMIN roles for access control")
    
    all_results = []
    
    # Test each system
    for system_name, rag_system in systems_to_test:
        try:
            # Test as user
            user_results = benchmark_search(rag_system, system_name, test_queries, "user")
            all_results.append(user_results)
            
            # Test as admin
            admin_results = benchmark_search(rag_system, system_name, test_queries, "admin")
            all_results.append(admin_results)
            
        except Exception as e:
            print(f"❌ Error testing {system_name}: {e}")
        finally:
            try:
                rag_system.close()
            except:
                pass
    
    # Display comparison results
    print("\n" + "=" * 80)
    print("📊 PERFORMANCE COMPARISON RESULTS")
    print("=" * 80)
    
    for result in all_results:
        print(f"\n🔹 {result['system']} ({result['role'].upper()} role)")
        print(f"   Average query time: {result['avg_query_time']:.3f}s")
        print(f"   Fastest query:      {result['min_query_time']:.3f}s")
        print(f"   Slowest query:      {result['max_query_time']:.3f}s")
        print(f"   Total results:      {result['total_results']}")
        print(f"   Average score:      {result['avg_result_score']:.3f}")
    
    # Role-based access comparison
    print(f"\n🔐 ACCESS CONTROL COMPARISON")
    print("-" * 40)
    
    for system_name in ["Qdrant", "Weaviate"]:
        user_res = next((r for r in all_results if r['system'] == system_name and r['role'] == 'user'), None)
        admin_res = next((r for r in all_results if r['system'] == system_name and r['role'] == 'admin'), None)
        
        if user_res and admin_res:
            print(f"\n{system_name}:")
            print(f"  User results:  {user_res['total_results']}")
            print(f"  Admin results: {admin_res['total_results']}")
            print(f"  Admin sees {admin_res['total_results'] - user_res['total_results']} more results")
    
    # Speed winner
    if len(all_results) >= 2:
        fastest_user = min((r for r in all_results if r['role'] == 'user'), key=lambda x: x['avg_query_time'])
        fastest_admin = min((r for r in all_results if r['role'] == 'admin'), key=lambda x: x['avg_query_time'])
        
        print(f"\n🏆 SPEED WINNERS")
        print(f"   User queries:  {fastest_user['system']} ({fastest_user['avg_query_time']:.3f}s avg)")
        print(f"   Admin queries: {fastest_admin['system']} ({fastest_admin['avg_query_time']:.3f}s avg)")
    
    print(f"\n✅ Comparison complete!")

if __name__ == "__main__":
    compare_systems() 