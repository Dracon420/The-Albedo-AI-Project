"""
Main query pipeline. Flow:
  1. Detect if Verify protocol is needed (hardware keywords).
  2a. Verify path  → run_verify() → send synthesis_prompt to bridge_chat().
  2b. Standard path → query RAG collections → build augmented prompt → bridge_chat().
"""

from albedo.rag.retriever import query_all
from albedo.web.search import web_search, format_web_results
from albedo.verify import is_hardware_query, run_verify
from albedo.bridge import bridge_chat


def _build_standard_prompt(query: str, rag_results: dict, web_results: list[dict]) -> str:
    sections = []

    for collection, chunks in rag_results.items():
        if not chunks:
            continue
        label = collection.replace("_", " ").title()
        block = "\n\n".join(
            f"({c['source']})\n{c['text'].strip()}" for c in chunks
        )
        sections.append(f"--- LOCAL {label.upper()} KNOWLEDGE ---\n{block}")

    if web_results:
        sections.append(f"--- WEB REFERENCE ---\n{format_web_results(web_results)}")

    context = "\n\n".join(sections) if sections else "No relevant local or web context found."

    return f"""{context}

--- USER QUERY ---
{query}

Answer using the context above. Cite sources where relevant."""


def run(query: str, use_web: bool = False) -> str:
    if is_hardware_query(query):
        print("[Albedo] Verify protocol engaged.")
        verify_data = run_verify(query)
        return bridge_chat(verify_data["synthesis_prompt"])

    # Skip RAG for very short inputs (greetings, single words) -- they have
    # no useful embedding match and can cause n_results=0 crashes.
    rag_results = {} if len(query) < 5 else query_all(query)
    web_results = web_search(query) if use_web else []

    prompt = _build_standard_prompt(query, rag_results, web_results)
    return bridge_chat(prompt)
