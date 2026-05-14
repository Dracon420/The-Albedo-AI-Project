# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Identity

**Albedo** is a Spartan-Class local AI assistant with Hybrid Retrieval-Augmented Generation (Hybrid RAG).

- **Wake word:** "Cortana"
- **Purpose:** A locally-run assistant that combines indexed local knowledge with live web search to maximize answer accuracy.

## Hardware Target

| Component | Spec |
|-----------|------|
| OS | Windows 11 |
| GPU | NVIDIA RTX 2060 6 GB VRAM |
| RAM | 16 GB (upgrading to 32 GB) |

VRAM is the primary constraint. Model selection and quantization levels must stay within the 6 GB envelope, leaving headroom for ChromaDB embeddings and Faster-Whisper inference running concurrently.

## Stack

| Layer | Technology |
|-------|------------|
| LLM runtime | Ollama |
| Agent / code execution | Open Interpreter (web search tools enabled) |
| Vector store | ChromaDB |
| Speech-to-text | Faster-Whisper |
| Wake word detection | OpenWakeWord |

## Architecture: Hybrid RAG

Albedo uses a two-track retrieval pipeline before generating any response:

1. **Local RAG (ChromaDB)** — Indexes files from local directories. The three knowledge domains are:
   - 3D printing files (STLs, slicer configs, print profiles)
   - Exotic OS Python source code
   - Reptile husbandry notes and records

2. **Web RAG (Open Interpreter web search)** — Queries the web to verify or supplement local results. Primary use cases:
   - Cross-referencing external hardware specifications
   - Checking live code documentation and changelogs

The retrieval flow is: wake word detected → STT via Faster-Whisper → query both ChromaDB and web search → merge/rank results → pass augmented context to Ollama → speak/display response.

## Key Design Constraints

- All inference must run **offline-capable** (web search is additive, not required).
- ChromaDB collections should be scoped per knowledge domain so indexing and retrieval can be targeted independently.
- Open Interpreter's web search integration must be the sanctioned path for external data — do not add a separate HTTP client or scraping layer.
- Wake word pipeline (OpenWakeWord → Faster-Whisper) runs as a persistent listener; keep its memory footprint minimal given the 6 GB VRAM ceiling.
