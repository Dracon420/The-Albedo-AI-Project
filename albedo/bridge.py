from interpreter import interpreter
from albedo.config import OLLAMA_MODEL, OLLAMA_BASE_URL
from albedo.web.search import web_search, format_web_results

_BRIDGE_SYSTEM_ADDENDUM = """
You are Albedo, a Spartan-Class local AI assistant. You have full Bridge Control over this
Windows desktop: you can run shell commands, write and execute code, move files, open
applications, and interact with the OS. You also have a web_search tool — call it any time
you need live external data.

To use web search, emit a Python code block like:
    results = web_search("your query here")
    print(results)

Never guess at hardware specs or code documentation — always cross-reference with web_search
when you are uncertain.
"""


def _build_interpreter() -> interpreter:
    interpreter.llm.model = f"ollama/{OLLAMA_MODEL}"
    interpreter.llm.api_base = OLLAMA_BASE_URL
    interpreter.llm.supports_functions = False

    interpreter.os = True
    interpreter.auto_run = True
    interpreter.force_task_completion = True

    interpreter.system_message += _BRIDGE_SYSTEM_ADDENDUM

    # Inject web_search into the interpreter's execution namespace so that
    # any code block it generates can call it directly.
    interpreter.computer.run("python", "pass")  # warm up the kernel
    interpreter.computer.run(
        "python",
        "from albedo.web.search import web_search, format_web_results",
    )

    return interpreter


_instance: interpreter | None = None


def get_interpreter() -> interpreter:
    global _instance
    if _instance is None:
        _instance = _build_interpreter()
    return _instance


def bridge_chat(message: str) -> str:
    interp = get_interpreter()
    response_chunks = interp.chat(message, stream=True, display=False)
    parts = []
    for chunk in response_chunks:
        if isinstance(chunk, dict) and chunk.get("type") == "message":
            parts.append(chunk.get("content", ""))
    return "".join(parts).strip()
