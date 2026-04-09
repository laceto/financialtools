# CLAUDE.md — Agent Router

This project is a **fundamental stock analysis library** (Yahoo Finance → scored metrics → LLM assessments).

## Commands

```bash
pip install -e .                                              # install (editable)
pip install -r requirements.txt                               # all deps
python -m unittest discover -s tests                          # run all tests
python -m unittest tests/test_processor.py                    # single test file
streamlit run app.py                                          # Streamlit UI
python scripts/run_analysis.py --ticker AAPL --sector "Technology Services"
python scripts/run_analysis.py --list-sectors
python -m unittest tests/test_financial_agent.py              # agents/ tests
```

Requires `.env` with `OPENAI_API_KEY`.

---

## Route to the Right Context

Pick your task, load the file.

| Task | Load |
|---|---|
| Writing or modifying code (features, metrics, models, pipelines) | `coding-rules.md` |
| Diagnosing failures, tracing NaN/empty output, LLM errors | `debugging-rules.md` |
| Understanding module map, data flows, or architecture | `architecture.md` |
| Working on the multi-agent LangGraph workflow | `agents/AGENTS.md` |

**Load only the file for your task. Do not load all files.**

If unsure which applies, ask rather than guessing.
