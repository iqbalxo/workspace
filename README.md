# Offline Support Pipeline

Replayable offline pipeline for support ticket triage, deterministic retrieval, drafting, review, checks, and final response packaging.

## Requirements

- Python 3.11+
- OpenRouter API key in `.env`

## Setup

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Environment

Create `.env`:

```bash
OPENROUTER_API_KEY=your_key
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

## Run Pipeline

```bash
.venv\Scripts\python main.py
```

This generates:

- `triage.json`
- `retrieval_results.json`
- `draft_responses.json`
- `review_results.json`
- `response_checks.json`
- `final_responses.json`
- `llm_calls.jsonl`

## Validate Outputs

```bash
.venv\Scripts\python validate.py
```

The validator checks artifact existence, JSON validity, per-ticket LLM stage records, retrieval-before-drafting order, citation grounding, and routing consistency for failed checks/reviews.
