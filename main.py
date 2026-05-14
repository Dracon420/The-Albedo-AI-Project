"""
Albedo — Spartan-Class Local Assistant

Usage:
    python main.py              # interactive text chat
    python main.py --voice      # wake word + voice pipeline (requires Piper + mic)
    python main.py --index      # re-index local directories then exit
    python main.py --web QUERY  # one-shot query with web search forced on
"""

import argparse
import sys


def cmd_index():
    from albedo.rag.indexer import index_all
    print("Indexing local directories into ChromaDB...")
    results = index_all()
    for collection, count in results.items():
        print(f"  {collection}: {count} new chunks indexed")
    print("Done.")


def cmd_query(query: str, use_web: bool):
    from albedo.pipeline import run
    print(f"\n[Albedo] {'(web) ' if use_web else ''}{query}\n")
    response = run(query, use_web=use_web)
    print(response)


def cmd_chat():
    from albedo.pipeline import run
    print("Albedo online. Type 'exit' to quit, prefix with 'web:' to force web search.\n")
    while True:
        try:
            raw = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAlbedo offline.")
            sys.exit(0)

        if not raw:
            continue
        if raw.lower() == "exit":
            print("Albedo offline.")
            break

        use_web = raw.lower().startswith("web:")
        query = raw[4:].strip() if use_web else raw

        response = run(query, use_web=use_web)
        print(f"\nAlbedo: {response}\n")


def cmd_voice(use_web: bool):
    from albedo.listener import start
    start(use_web=use_web)


def main():
    parser = argparse.ArgumentParser(description="Albedo local AI assistant")
    parser.add_argument("--index", action="store_true", help="Index local directories and exit")
    parser.add_argument("--voice", action="store_true", help="Start voice listener (wake word mode)")
    parser.add_argument("--web", metavar="QUERY", nargs="?", const=True,
                        help="Force web search. With QUERY: one-shot mode. With --voice: web always on.")
    args = parser.parse_args()

    if args.index:
        cmd_index()
    elif args.voice:
        use_web = args.web is not None
        cmd_voice(use_web=use_web)
    elif isinstance(args.web, str):
        cmd_query(args.web, use_web=True)
    else:
        cmd_chat()


if __name__ == "__main__":
    main()
