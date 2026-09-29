#!/usr/bin/env python3
"""
Simple test script for the LearningSteps API
Tests all available endpoints
"""

import os
import sys
import requests
import json
from datetime import datetime

# API base URL (override for a deployed instance: BASE_URL=https://<ip> python test_api.py)
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_URL = f"{BASE_URL}/api"
TIMEOUT = 10  # seconds per request

# Requests that did not return 2xx; a non-empty list makes the script exit 1 (CI gate)
FAILURES = []

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def print_response(response):
    """Pretty print API response"""
    print(f"Status Code: {response.status_code}")
    if not response.ok:
        FAILURES.append(f"{response.request.method} {response.request.path_url} -> {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2, default=str)}")
    except ValueError:  # body is not JSON
        print(f"Response: {response.text}")

def test_create_entry():
    """Test POST /api/entries - Create a new journal entry"""
    print_section("TEST 1: Create a New Entry")
    
    entry_data = {
        "work": "Learned FastAPI basics and tested API endpoints",
        "struggle": "Understanding async/await patterns in Python",
        "intention": "Build a complete test suite for the API"
    }
    
    response = requests.post(f"{API_URL}/entries", json=entry_data, timeout=TIMEOUT)
    print_response(response)
    
    if response.status_code == 200:
        return response.json().get("entry", {}).get("id")
    return None

def test_get_all_entries():
    """Test GET /api/entries - Get all journal entries"""
    print_section("TEST 2: Get All Entries")
    
    response = requests.get(f"{API_URL}/entries", timeout=TIMEOUT)
    print_response(response)
    
    if response.status_code == 200:
        entries = response.json().get("entries", [])
        if entries:
            return entries[0].get("id")
    return None

def test_get_single_entry(entry_id):
    """Test GET /api/entries/{entry_id} - Get a single entry"""
    print_section("TEST 3: Get Single Entry")
    
    if not entry_id:
        print("⚠️  No entry ID available, skipping test")
        return
    
    response = requests.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT)
    print_response(response)

def test_update_entry(entry_id):
    """Test PATCH /api/entries/{entry_id} - Update an entry"""
    print_section("TEST 4: Update Entry")
    
    if not entry_id:
        print("⚠️  No entry ID available, skipping test")
        return
    
    update_data = {
        "work": "Updated: Completed API testing script"
    }
    
    response = requests.patch(f"{API_URL}/entries/{entry_id}", json=update_data, timeout=TIMEOUT)
    print_response(response)

def test_delete_single_entry(entry_id):
    """Test DELETE /api/entries/{entry_id} - Delete a specific entry"""
    print_section("TEST 5: Delete Single Entry")
    
    if not entry_id:
        print("⚠️  No entry ID available, skipping test")
        return
    
    response = requests.delete(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT)
    print_response(response)

def test_delete_all_entries():
    """Test DELETE /api/entries - Delete all entries"""
    print_section("TEST 6: Delete All Entries")
    
    response = requests.delete(f"{API_URL}/entries", timeout=TIMEOUT)
    print_response(response)

def test_web_ui():
    """Test GET / - the web UI is served as HTML"""
    print_section("Web UI")

    response = requests.get(f"{BASE_URL}/", timeout=TIMEOUT)
    print(f"Status Code: {response.status_code}")
    content_type = response.headers.get("content-type", "")
    print(f"Content-Type: {content_type}")
    if not response.ok or not content_type.startswith("text/html"):
        FAILURES.append(f"GET / -> {response.status_code} {content_type}")

def test_api_health():
    """Check if API is accessible"""
    print_section("API Health Check")
    
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=TIMEOUT)
        if response.status_code == 200:
            print("✅ API is running and accessible")
            return True
        else:
            print(f"⚠️  API returned status code: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API. Make sure it's running on http://localhost:8000")
        return False

def main():
    """Run all API tests"""
    print("\n🚀 Starting LearningSteps API Tests")
    print(f"Testing API at: {BASE_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if API is running
    if not test_api_health():
        print("\n❌ Tests aborted: API is not accessible")
        print("💡 Tip: Run './start.sh' to start the API")
        sys.exit(1)
    
    test_web_ui()

    # Test creating an entry
    created_entry_id = test_create_entry()
    
    # Test getting all entries
    entry_id = test_get_all_entries()
    
    # Use the created entry ID or the first available entry ID
    test_id = created_entry_id or entry_id
    
    # Test getting a single entry
    test_get_single_entry(test_id)
    
    # Test updating an entry
    test_update_entry(test_id)
    
    # Test deleting a single entry (creates a new one first to avoid deleting all data)
    temp_entry_id = test_create_entry()
    test_delete_single_entry(temp_entry_id)
    
    # Uncomment below to test delete all entries (warning: deletes all data!)
    # print("\n⚠️  Warning: The next test will delete ALL entries from the database")
    # test_delete_all_entries()
    
    if FAILURES:
        print_section(f"❌ {len(FAILURES)} request(s) failed")
        print("\n".join(FAILURES))
        sys.exit(1)

    print_section("✅ Tests Complete!")
    print("💡 Tip: Visit http://localhost:8000/docs to explore the API interactively")

if __name__ == "__main__":
    main()

