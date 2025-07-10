#!/usr/bin/env python3
"""
Test script to verify the optimization improvements
"""

import requests
import time
import json

BASE_URL = "http://localhost:5000"

def test_old_vs_new_approach():
    """Test the performance difference between old and new approach"""
    
    print("🧪 Testing API Performance Optimization")
    print("=" * 50)
    
    # Test 1: Old approach (multiple API calls)
    print("\n📊 Testing OLD approach (multiple separate API calls):")
    start_time = time.time()
    
    try:
        # Simulate old approach - multiple API calls
        response1 = requests.get(f"{BASE_URL}/dashboard/api/campaigns")
        response2 = requests.get(f"{BASE_URL}/dashboard/api/rules/list")
        response3 = requests.get(f"{BASE_URL}/dashboard/api/dashboard-stats")
        response4 = requests.get(f"{BASE_URL}/dashboard/api/chart-data")
        
        old_time = time.time() - start_time
        print(f"   ⏱️  Time taken: {old_time:.2f} seconds")
        print(f"   📡 API calls made: 4")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        old_time = float('inf')
    
    # Test 2: New approach (single API call)
    print("\n🚀 Testing NEW approach (single optimized API call):")
    start_time = time.time()
    
    try:
        # New approach - single API call
        response = requests.get(f"{BASE_URL}/dashboard/api/get-all-data")
        
        new_time = time.time() - start_time
        print(f"   ⏱️  Time taken: {new_time:.2f} seconds")
        print(f"   📡 API calls made: 1")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                cached_data = data.get('data', {})
                print(f"   📋 Campaigns loaded: {len(cached_data.get('campaigns', []))}")
                print(f"   📝 Rules loaded: {len(cached_data.get('rules', []))}")
                print(f"   📊 Dashboard stats: {'✅' if cached_data.get('dashboard_stats') else '❌'}")
                print(f"   📈 Chart data: {'✅' if cached_data.get('chart_data') else '❌'}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        new_time = float('inf')
    
    # Performance comparison
    print("\n📈 PERFORMANCE COMPARISON:")
    print("=" * 30)
    
    if old_time != float('inf') and new_time != float('inf'):
        improvement = ((old_time - new_time) / old_time) * 100
        print(f"   🏃 Speed improvement: {improvement:.1f}%")
        print(f"   ⚡ Times faster: {old_time/new_time:.1f}x")
    
    if new_time < old_time:
        print("   ✅ NEW approach is FASTER! 🎉")
    else:
        print("   ⚠️  OLD approach was faster (unexpected)")
    
    print(f"\n   📊 Old approach: {old_time:.2f}s (4 API calls)")
    print(f"   🚀 New approach: {new_time:.2f}s (1 API call)")

def test_cache_freshness():
    """Test cache freshness functionality"""
    print("\n\n🔄 Testing Cache Freshness")
    print("=" * 30)
    
    try:
        # First call - should populate cache
        print("   📥 First call (populating cache)...")
        start_time = time.time()
        response1 = requests.get(f"{BASE_URL}/dashboard/api/get-all-data")
        first_time = time.time() - start_time
        
        # Second call - should use cache
        print("   📋 Second call (using cache)...")
        start_time = time.time()
        response2 = requests.get(f"{BASE_URL}/dashboard/api/get-all-data")
        second_time = time.time() - start_time
        
        print(f"   ⏱️  First call: {first_time:.2f}s")
        print(f"   ⏱️  Second call: {second_time:.2f}s")
        
        if second_time < first_time:
            print("   ✅ Cache is working! Second call was faster.")
        else:
            print("   ⚠️  Cache might not be working as expected.")
            
    except Exception as e:
        print(f"   ❌ Error testing cache: {e}")

if __name__ == "__main__":
    print("🚀 MetaAds Automation - Performance Test")
    print("Make sure the Flask app is running on localhost:5000")
    print("Press Enter to start testing...")
    input()
    
    test_old_vs_new_approach()
    test_cache_freshness()
    
    print("\n" + "=" * 50)
    print("✅ Performance testing completed!")
    print("Check the results above to see the improvements.")
