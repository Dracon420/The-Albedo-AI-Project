# -*- coding: utf-8 -*-
"""
Smoke test -- verifies two critical paths without requiring Ollama or audio hardware:

  TEST 1 -- Local RAG:
    Index tests/fixtures/ into ChromaDB -> query -> confirm fixture content retrieved.

  TEST 2 -- Live web search:
    DuckDuckGo search for RTX 2060 specs -> confirm results returned with URLs.

  TEST 3 -- Verify protocol routing:
    Hardware keyword detection fires correctly.

  TEST 4 -- Memory footprint:
    Index runs within expected RAM budget (reports peak delta in MB).

Run from repo root:
    python tests/smoke_test.py
"""

import sys
import os
import gc
import tracemalloc
import shutil
import traceback

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "  [PASS]"
FAIL = "  [FAIL]"
INFO = "  [INFO]"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    results.append((name, passed, detail))
    status = PASS if passed else FAIL
    print(f"{status}  {name}" + (f"\n          {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Test 1: Local RAG index + query
# --------------------------------------------------------------------------

print("\n== Test 1: Local RAG (index -> query) ==")
try:
    from albedo.rag.indexer import index_exotic_os
    from albedo.rag.retriever import query_exotic_os

    chroma_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    if os.path.exists(chroma_path):
        shutil.rmtree(chroma_path)

    indexed = index_exotic_os()
    record("index_exotic_os() runs without error", True, f"{indexed} chunks indexed")

    if indexed == 0:
        record("Fixture file was indexed", False, "0 chunks -- check EXOTIC_OS_PATH in .env")
    else:
        rag_results = query_exotic_os("GPU temperature throttling RTX 2060", top_k=3)
        has_results = len(rag_results) > 0
        record("query_exotic_os() returns results", has_results,
               f"{len(rag_results)} chunks returned")

        if has_results:
            top = rag_results[0]
            contains_fixture = "RTX 2060" in top["text"] or "GPU" in top["text"]
            record(
                "Top result contains fixture content",
                contains_fixture,
                f"Source: {top['source']} | Score: {top['score']:.4f}",
            )

except Exception:
    record("Local RAG pipeline", False, traceback.format_exc().splitlines()[-1])
    traceback.print_exc()


# --------------------------------------------------------------------------
# Test 2: Live web search
# --------------------------------------------------------------------------

print("\n== Test 2: Live web search (DuckDuckGo) ==")
try:
    from albedo.web.search import web_search, format_web_results

    search_results = web_search("NVIDIA RTX 2060 VRAM specifications", max_results=3)

    has_results = len(search_results) > 0
    record("web_search() returns results", has_results, f"{len(search_results)} results")

    if has_results:
        has_urls = all(r.get("url") for r in search_results)
        record("All results have URLs", has_urls)

        has_snippets = all(r.get("snippet") for r in search_results)
        record("All results have snippets", has_snippets)

        formatted = format_web_results(search_results)
        record("format_web_results() produces output", bool(formatted.strip()))

        print(f"\n{INFO}  Top web result:")
        print(f"          Title:   {search_results[0]['title'][:80]}")
        print(f"          URL:     {search_results[0]['url'][:80]}")
        print(f"          Snippet: {search_results[0]['snippet'][:120]}...")

except Exception:
    record("Web search pipeline", False, traceback.format_exc().splitlines()[-1])
    traceback.print_exc()


# --------------------------------------------------------------------------
# Test 3: Verify protocol keyword routing
# --------------------------------------------------------------------------

print("\n== Test 3: Verify protocol keyword routing ==")
try:
    from albedo.verify import is_hardware_query

    cases = [
        ("My GPU is overheating", True),
        ("How do I print a benchy?", False),
        ("BSOD after driver update", True),
        ("What is reptile humidity?", False),
        ("RTX 2060 temperature throttling", True),
    ]
    for query, expected in cases:
        got = is_hardware_query(query)
        ok = got == expected
        record(
            f"is_hardware_query({query!r})",
            ok,
            f"expected={expected}, got={got}",
        )

except Exception:
    record("Verify routing", False, traceback.format_exc().splitlines()[-1])


# --------------------------------------------------------------------------
# Test 4: Indexer RAM footprint
# --------------------------------------------------------------------------

print("\n== Test 4: Indexer RAM footprint ==")
try:
    from albedo.rag.indexer import index_exotic_os as _reindex

    shutil.rmtree(chroma_path, ignore_errors=True)
    gc.collect()

    tracemalloc.start()
    _reindex()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    under_budget = peak_mb < 200
    record(
        "Peak RAM delta during indexing",
        under_budget,
        f"{peak_mb:.1f} MB peak (budget: <200 MB for fixture set)",
    )

except Exception:
    record("RAM footprint test", False, traceback.format_exc().splitlines()[-1])


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

print("\n== Summary ==")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n  {passed}/{total} tests passed\n")

sys.exit(0 if passed == total else 1)
