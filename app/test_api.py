#!/usr/bin/env python3
"""
End-to-end checks for the LearningSteps API: CRUD, authentication, per-user
isolation and the HTTP hardening. Runs against a live stack.

Needs two existing accounts (create them with api/create_user.py):
  TEST_USER / TEST_PASSWORD     default: alice / alice-password-1
  TEST_USER2 / TEST_PASSWORD2   default: bob / bob-password-123

  BASE_URL=http://localhost:8000 python test_api.py
"""

import os
import sys
import uuid

import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_URL = f"{BASE_URL}/api"
TIMEOUT = 10  # seconds per request

USER1 = (os.getenv("TEST_USER", "alice"), os.getenv("TEST_PASSWORD", "alice-password-1"))
USER2 = (os.getenv("TEST_USER2", "bob"), os.getenv("TEST_PASSWORD2", "bob-password-123"))

FAILURES = []

ENTRY = {
    "work": "Learned FastAPI basics and tested API endpoints",
    "struggle": "Understanding async/await patterns in Python",
    "intention": "Build a complete test suite for the API",
}


def section(title):
    print("\n" + "=" * 60 + f"\n  {title}\n" + "=" * 60)


def check(name, condition, detail=""):
    print(f"  {'✅' if condition else '❌'} {name}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def expect(name, response, status):
    check(f"{name} -> {status}", response.status_code == status, f"got {response.status_code}: {response.text[:200]}")
    return response


def login(username, password):
    s = requests.Session()
    r = s.post(f"{API_URL}/auth/login", json={"username": username, "password": password}, timeout=TIMEOUT)
    expect(f"login {username}", r, 200)
    return s


def test_public_surface():
    section("Public surface")
    r = requests.get(f"{BASE_URL}/", timeout=TIMEOUT)
    expect("GET / (web UI)", r, 200)
    check("UI is HTML", r.headers.get("content-type", "").startswith("text/html"))
    csp = r.headers.get("content-security-policy", "")
    check("UI has a CSP without unsafe-inline scripts", "script-src 'self'" in csp and "frame-ancestors 'none'" in csp)
    check("X-Frame-Options DENY", r.headers.get("x-frame-options") == "DENY")
    check("nosniff", r.headers.get("x-content-type-options") == "nosniff")
    check("X-Request-ID present", bool(r.headers.get("x-request-id")))

    r = expect("GET /api/auth/config", requests.get(f"{API_URL}/auth/config", timeout=TIMEOUT), 200)
    check("config lists sign-in methods", set(r.json()) == {"password", "entra"})
    expect("Entra callback without a sign-in in progress",
           requests.get(f"{API_URL}/auth/entra/callback", params={"code": "x", "state": "y"},
                        allow_redirects=False, timeout=TIMEOUT),
           303 if r.json()["entra"] else 404)

    # API docs are for signed-in users (unless ENABLE_DOCS=true, which the
    # stack under test does not set): anonymous gets a plain 404.
    expect("GET /docs without session", requests.get(f"{BASE_URL}/docs", timeout=TIMEOUT), 404)
    expect("GET /openapi.json without session", requests.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT), 404)

    expect("GET /api/entries without session", requests.get(f"{API_URL}/entries", timeout=TIMEOUT), 401)
    expect("GET /api/auth/me without session", requests.get(f"{API_URL}/auth/me", timeout=TIMEOUT), 401)
    r = requests.get(f"{API_URL}/entries", cookies={"session": "forged", "__Host-session": "forged"}, timeout=TIMEOUT)
    expect("forged session cookie", r, 401)


def test_login_rules():
    section("Login")
    r = requests.post(f"{API_URL}/auth/login", json={"username": USER1[0], "password": "wrong-password"}, timeout=TIMEOUT)
    expect("wrong password", r, 401)
    unknown = requests.post(f"{API_URL}/auth/login", json={"username": "nobody-" + uuid.uuid4().hex[:8], "password": "x"}, timeout=TIMEOUT)
    expect("unknown user", unknown, 401)
    check("same message for unknown user and wrong password", r.json() == unknown.json())

    # Throttling: a throwaway username, so real accounts are not locked out.
    victim = "throttle-" + uuid.uuid4().hex[:8]
    statuses = [
        requests.post(f"{API_URL}/auth/login", json={"username": victim, "password": "guess"}, timeout=TIMEOUT).status_code
        for _ in range(6)
    ]
    check("6th failed login is throttled (429)", statuses[-1] == 429, str(statuses))


def test_docs(s):
    section("API docs (signed in)")
    r = expect("GET /docs", s.get(f"{BASE_URL}/docs", timeout=TIMEOUT), 200)
    csp = r.headers.get("content-security-policy", "")
    script_src = next((d for d in csp.split(";") if d.strip().startswith("script-src")), "")
    check("docs CSP allows inline scripts only by hash",
          "'sha256-" in script_src and "unsafe-inline" not in script_src)
    check("Swagger UI is served from this origin", "/assets/swagger/swagger-ui-bundle.js" in r.text
          and "cdn." not in r.text)
    expect("Swagger UI bundle", s.get(f"{BASE_URL}/assets/swagger/swagger-ui-bundle.js", timeout=TIMEOUT), 200)
    r = expect("GET /openapi.json", s.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT), 200)
    check("schema lists the entries API", "/api/entries" in r.json().get("paths", {}))
    check("/me points to the docs", s.get(f"{API_URL}/auth/me", timeout=TIMEOUT).json().get("docs_url") == "/docs")


def test_crud(s):
    section("CRUD")
    r = expect("POST /api/entries", s.post(f"{API_URL}/entries", json=ENTRY, timeout=TIMEOUT), 200)
    entry_id = r.json()["entry"]["id"]

    r = expect("GET /api/entries", s.get(f"{API_URL}/entries", timeout=TIMEOUT), 200)
    body = r.json()
    check("list has count/total/limit/offset", {"entries", "count", "total", "limit", "offset"} <= body.keys())
    check("API responses are not cached", r.headers.get("cache-control") == "no-store")

    expect("GET /api/entries/{id}", s.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 200)
    r = expect("PATCH /api/entries/{id}", s.patch(f"{API_URL}/entries/{entry_id}", json={"work": "Updated: Completed API testing script"}, timeout=TIMEOUT), 200)
    check("PATCH keeps fields that were not sent", r.json()["struggle"] == ENTRY["struggle"])

    q = s.get(f"{API_URL}/entries", params={"q": "Completed API testing"}, timeout=TIMEOUT).json()
    check("search finds the updated entry", any(e["id"] == entry_id for e in q["entries"]))
    q = s.get(f"{API_URL}/entries", params={"q": "%"}, timeout=TIMEOUT).json()
    check("LIKE wildcards in search are literal", q["count"] == 0, str(q["count"]))

    expect("DELETE /api/entries/{id}", s.delete(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 200)
    expect("deleted entry is gone", s.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 404)
    expect("POST restore", s.post(f"{API_URL}/entries/{entry_id}/restore", timeout=TIMEOUT), 200)
    expect("restored entry is back", s.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 200)
    return entry_id


def test_validation(s):
    section("Input validation")
    expect("non-UUID entry id", s.get(f"{API_URL}/entries/not-a-uuid", timeout=TIMEOUT), 422)
    expect("page size over 100", s.get(f"{API_URL}/entries", params={"limit": 1000}, timeout=TIMEOUT), 422)
    expect("huge offset", s.get(f"{API_URL}/entries", params={"offset": 10**9}, timeout=TIMEOUT), 422)
    expect("unknown sort column", s.get(f"{API_URL}/entries", params={"sort": "id; drop table entries"}, timeout=TIMEOUT), 422)
    expect("too short field", s.post(f"{API_URL}/entries", json={**ENTRY, "work": "ab"}, timeout=TIMEOUT), 422)
    expect("unknown PATCH field", s.patch(f"{API_URL}/entries/{uuid.uuid4()}", json={"user_id": "x"}, timeout=TIMEOUT), 422)
    big = {**ENTRY, "work": "x" * 20_000}
    expect("body over 16 KiB", s.post(f"{API_URL}/entries", json=big, timeout=TIMEOUT), 413)


def test_csrf(s):
    section("Cross-site request protection")
    r = s.post(f"{API_URL}/entries", json=ENTRY, headers={"Origin": "https://evil.example"}, timeout=TIMEOUT)
    expect("foreign Origin", r, 403)
    r = s.delete(f"{API_URL}/entries", headers={"Sec-Fetch-Site": "cross-site"}, timeout=TIMEOUT)
    expect("Sec-Fetch-Site: cross-site", r, 403)
    r = s.post(f"{API_URL}/entries", data="work=a&struggle=b&intention=c",
               headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    expect("form-encoded body", r, 415)


def test_isolation(s1, entry_id):
    section("Per-user isolation")
    s2 = login(*USER2)
    expect("other user cannot GET", s2.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 404)
    expect("other user cannot PATCH", s2.patch(f"{API_URL}/entries/{entry_id}", json={"work": "hijacked!"}, timeout=TIMEOUT), 404)
    expect("other user cannot DELETE", s2.delete(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 404)
    listing = s2.get(f"{API_URL}/entries", params={"limit": 100}, timeout=TIMEOUT).json()
    check("other user's list does not contain it", all(e["id"] != entry_id for e in listing["entries"]))
    expect("other user's DELETE all", s2.delete(f"{API_URL}/entries", timeout=TIMEOUT), 200)
    expect("first user's entry survives it", s1.get(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT), 200)

    expect("logout", s2.post(f"{API_URL}/auth/logout", timeout=TIMEOUT), 204)
    expect("session is dead after logout", s2.get(f"{API_URL}/entries", timeout=TIMEOUT), 401)


def main():
    print(f"\n🚀 LearningSteps API tests against {BASE_URL}")
    try:
        requests.get(f"{BASE_URL}/healthz", timeout=TIMEOUT).raise_for_status()
    except requests.RequestException as e:
        print(f"❌ API is not reachable: {e}")
        sys.exit(1)

    test_public_surface()
    test_login_rules()
    s1 = login(*USER1)
    test_docs(s1)
    entry_id = test_crud(s1)
    test_validation(s1)
    test_csrf(s1)
    test_isolation(s1, entry_id)
    s1.delete(f"{API_URL}/entries/{entry_id}", timeout=TIMEOUT)

    if FAILURES:
        section(f"❌ {len(FAILURES)} check(s) failed")
        print("\n".join(FAILURES))
        sys.exit(1)
    section("✅ All checks passed")


if __name__ == "__main__":
    main()
