# -*- coding: utf-8 -*-
"""
Smoke test — verifies critical paths without requiring Ollama or audio hardware.

  TEST 1 — Obsidian vault RAG:
    Write a temp .md fixture → index into isolated temp ChromaDB → query →
    confirm fixture content is retrieved.

  TEST 2 — Live web search:
    DuckDuckGo search for RTX 2060 specs → confirm results returned with URLs.

  TEST 3 — Verify protocol routing:
    Hardware keyword detection fires correctly.

  TEST 4 — Memory footprint:
    Vault index runs within expected RAM budget.

Run from repo root:
    python tests/smoke_test.py
"""

import sys
import os
import gc
import tracemalloc
import shutil
import tempfile
import traceback
from pathlib import Path

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
# Test 1: Obsidian vault RAG — index -> query in an isolated temp DB
# --------------------------------------------------------------------------

print("\n== Test 1: Obsidian vault RAG (index -> query) ==")
tmp_vault = None
tmp_db    = None
try:
    import memory as _mem

    tmp_vault = tempfile.mkdtemp()
    tmp_db    = tempfile.mkdtemp()

    # Write a fixture note with distinctive content
    note = Path(tmp_vault) / "hardware_notes.md"
    note.write_text(
        "# GPU Notes\n\n"
        "The RTX 2060 has 6 GB GDDR6 VRAM. "
        "Temperature throttling begins around 83 degrees Celsius. "
        "Driver version 537 fixed the memory clock stability issue.",
        encoding="utf-8",
    )

    # Redirect memory.py's DB path to the temp dir for this test
    _orig_db = _mem.DB_PATH
    _mem.DB_PATH = tmp_db
    # Also reset the singleton collection cache if present
    try:
        _mem._EF_tried = False
        _mem._EF = None
    except AttributeError:
        pass

    from memory import index_obsidian_vault, search_memory

    status = index_obsidian_vault(tmp_vault)
    record("index_obsidian_vault() runs without error", True, status)

    chunks = search_memory("RTX 2060 temperature throttling", n_results=3)
    has_results = len(chunks) > 0
    record("search_memory() returns results", has_results,
           f"{len(chunks)} chunks returned")

    if has_results:
        contains_fixture = any(
            "RTX 2060" in c or "throttling" in c or "temperature" in c
            for c in chunks
        )
        record("Top result contains fixture content", contains_fixture,
               chunks[0][:120])

except Exception:
    record("Obsidian vault RAG pipeline", False,
           traceback.format_exc().splitlines()[-1])
    traceback.print_exc()
finally:
    # Restore the real DB path before any further tests
    try:
        import memory as _mem
        _mem.DB_PATH = _orig_db  # type: ignore[possibly-undefined]
    except Exception:
        pass
    if tmp_vault:
        shutil.rmtree(tmp_vault, ignore_errors=True)
    if tmp_db:
        shutil.rmtree(tmp_db, ignore_errors=True)


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
        ("My GPU is overheating",          True),
        ("How do I print a benchy?",        False),
        ("BSOD after driver update",        True),
        ("What is reptile humidity?",       False),
        ("RTX 2060 temperature throttling", True),
    ]
    for query, expected in cases:
        got = is_hardware_query(query)
        ok  = got == expected
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
tmp_vault4 = None
tmp_db4    = None
try:
    import memory as _mem

    tmp_vault4 = tempfile.mkdtemp()
    tmp_db4    = tempfile.mkdtemp()

    note4 = Path(tmp_vault4) / "big_note.md"
    note4.write_text("# RAM Test\n\n" + ("Sample content line.\n" * 500),
                     encoding="utf-8")

    _orig_db4 = _mem.DB_PATH
    _mem.DB_PATH = tmp_db4

    from memory import index_obsidian_vault as _reindex

    gc.collect()
    tracemalloc.start()
    _reindex(tmp_vault4)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    under_budget = peak_mb < 200
    record(
        "Peak RAM delta during indexing",
        under_budget,
        f"{peak_mb:.1f} MB peak (budget: <200 MB)",
    )

except Exception:
    record("RAM footprint test", False, traceback.format_exc().splitlines()[-1])
finally:
    try:
        import memory as _mem
        _mem.DB_PATH = _orig_db4  # type: ignore[possibly-undefined]
    except Exception:
        pass
    if tmp_vault4:
        shutil.rmtree(tmp_vault4, ignore_errors=True)
    if tmp_db4:
        shutil.rmtree(tmp_db4, ignore_errors=True)


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

print("\n== Summary ==")
passed = sum(1 for _, ok, _ in results if ok)
total  = len(results)
print(f"\n  {passed}/{total} tests passed\n")

sys.exit(0 if passed == total else 1)
