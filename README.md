# Offline Support Pipeline

Replayable offline pipeline for support ticket triage, deterministic retrieval, drafting, review, checks, and final response packaging.

## What This Project Does

This project runs a staged, offline AI-assisted support workflow over ticket and policy JSON files.

For each ticket it:

1. Classifies intent/priority/escalation (`triage`)
2. Retrieves relevant policy evidence deterministically (`retrieval`)
3. Drafts a customer response with policy citations (`drafting`)
4. Reviews draft quality/safety (`review`)
5. Applies deterministic guardrail checks (`response checks`)
6. Produces a final response pack with review routing (`finalization`)

The pipeline is replayable from disk inputs and writes machine-readable artifacts for every stage.

## Repository Structure

```text
.
├── config/
│   ├── drafting_rules.json
│   ├── finalization_rules.json
│   ├── response_check_rules.json
│   ├── reviewer_rules.json
│   └── triage_rules.json
├── support_pipeline/
│   ├── __init__.py
│   ├── artifact_store.py
│   ├── contracts.py
│   ├── drafting.py
│   ├── finalization.py
│   ├── pipeline.py
│   ├── response_checks.py
│   ├── retrieval.py
│   ├── reviewer.py
│   ├── settings.py
│   ├── stage_tracker.py
│   ├── types.py
│   └── validator.py
├── main.py
├── validate.py
├── tickets.json
├── policy_kb.json
├── requirements.txt
└── README.md
```

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

Expected terminal output on success:

```text
Current stage: RESPONSE_FINALISED
Tickets loaded: 4
Policies indexed: 5
Triage output: triage.json
Retrieval output: retrieval_results.json
Draft output: draft_responses.json
Response checks output: response_checks.json
Review output: review_results.json
Final responses output: final_responses.json
LLM call log: llm_calls.jsonl
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

Expected terminal output on success:

```text
VALIDATION PASSED
```

Example terminal output on failure:

```text
VALIDATION FAILED
- missing_artifacts:review_results.json
- llm_stage_count_error:review:T3
- draft_citation_outside_retrieval:T2:P99
```

The validator checks artifact existence, JSON validity, per-ticket LLM stage records, retrieval-before-drafting order, citation grounding, and routing consistency for failed checks/reviews.
