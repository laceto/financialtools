"""
run_agent.py — Interactive LangChain ReAct agent with financialtools tools
=========================================================================

Launches a REPL that lets you query the financialtools pipeline through a
LangChain agent.  The agent has access to five tools:

    list_available_tickers   — discover which tickers have been evaluated
    get_stock_metrics        — financial metrics + composite score
    get_sector_benchmarks    — peer-average benchmarks for a sector
    get_red_flags            — red-flag warnings for a ticker
    get_stock_regime_report  — full LLM bull/bear regime assessment

Usage
-----
    python scripts/run_agent.py                  # interactive REPL
    python scripts/run_agent.py --model gpt-4o   # override the LLM model

Prerequisites
-------------
- financial_data/ directory must exist with pipeline outputs.
  Run  python scripts/run_pipeline.py  first.
- .env file must contain OPENAI_API_KEY.
- Optional: set LANGSMITH_API_KEY + LANGSMITH_PROJECT for tracing.

Design invariants
-----------------
- Agent uses MemorySaver checkpointer with a fixed thread_id for the
  session — tool-call messages and results are preserved across turns.
- Each REPL turn passes only the new user message; the checkpointer
  supplies the full prior history internally.
- recursion_limit=20 caps runaway loops.
- Tokens stream to stdout as they are produced (stream_mode="messages").
- Tools never raise — they return {"error": "..."} JSON so the agent can
  reason about failures without a traceback breaking the loop.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging: console only for agent sessions
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("run_agent")

# ---------------------------------------------------------------------------
# Imports deferred until after load_dotenv so API keys are available
# ---------------------------------------------------------------------------
from langchain.agents import create_agent          # noqa: E402
from langchain_openai import ChatOpenAI            # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from financialtools.tools import TOOLS             # noqa: E402

# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "You are a fundamental stock analysis assistant powered by the financialtools library.\n\n"
    "You have access to five tools:\n"
    "  • list_available_tickers   — call this first to discover evaluated tickers\n"
    "  • get_stock_metrics        — financial metrics, composite score\n"
    "  • get_sector_benchmarks    — peer-average benchmarks for a sector\n"
    "  • get_red_flags            — warning signals for a ticker\n"
    "  • get_stock_regime_report  — full bull/bear LLM regime assessment\n\n"
    "Workflow guidelines:\n"
    "  1. When the user asks about a ticker you don't know is available, "
    "call list_available_tickers first.\n"
    "  2. For regime questions, use get_stock_regime_report — it already "
    "incorporates metrics, benchmarks, and red flags.\n"
    "  3. For targeted metric questions, use get_stock_metrics or "
    "get_sector_benchmarks directly.\n"
    "  4. If a tool returns {\"error\": ...}, explain the problem and suggest "
    "running the pipeline.\n"
    "  5. Always cite specific metric values when explaining your conclusions.\n"
)

# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def run_repl(model: str) -> None:
    """Start an interactive agent REPL session with persistent tool-call memory."""
    logger.info("Initialising agent with model '%s' and %d tools …", model, len(TOOLS))

    llm = ChatOpenAI(model=model, temperature=0)
    checkpointer = MemorySaver()

    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )

    # Fixed thread_id for the session — the checkpointer stores full message
    # history (including tool calls and results) keyed by this ID.
    config = {
        "configurable": {"thread_id": "financialtools-session"},
        "recursion_limit": 20,
    }

    print(f"\nFinancialtools Agent  (model: {model})")
    print("Type your question and press Enter.  Ctrl-C or type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Goodbye.")
            break

        print("\nAgent: ", end="", flush=True)

        try:
            # Stream tokens as they arrive; checkpointer handles full history.
            for chunk in agent.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="messages",
            ):
                token, _metadata = chunk
                if hasattr(token, "content") and token.content:
                    print(token.content, end="", flush=True)
        except Exception as exc:
            logger.error("Agent invocation failed: %s", exc, exc_info=True)
            print(f"[Agent error] {exc}", end="")

        print("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Interactive LangChain agent for fundamental stock analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--model",
        default="gpt-4.1-nano",
        metavar="MODEL",
        help="OpenAI model name (default: gpt-4.1-nano)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_repl(model=args.model)
