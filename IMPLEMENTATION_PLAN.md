# Support Pipeline Implementation Plan

## Objective

Build an offline, replayable support workflow that reads `tickets.json` and `policy_kb.json`, runs staged AI + deterministic processing, and produces traceable JSON artifacts for human review.

## Required Stage Flow

```text
INIT
 -> INPUTS_LOADED
 -> TICKETS_PARSED
 -> KB_INDEXED
 -> TICKET_TRIAGED
 -> EVIDENCE_RETRIEVED
 -> RESPONSE_DRAFTED
 -> RESPONSE_CHECKED
 -> RESPONSE_FINALISED
```

Final outputs are generated only after triage, retrieval, drafting, and deterministic checks are complete.

## Must-Have Requirements

1. Read `tickets.json` and `policy_kb.json` from disk.
2. Run one triage LLM call per ticket and save `triage.json`.
3. Perform deterministic retrieval before drafting and save `retrieval_results.json`.
4. Run one drafting LLM call per ticket and save `draft_responses.json`.
5. Run deterministic checks and save `response_checks.json`.
6. Generate `final_responses.json` with `ready` vs `needs_human_review`.
7. Log every LLM call in `llm_calls.jsonl` with:
   - `stage`
   - `ticket_id`
   - `timestamp`
   - `provider`
   - `model`
   - `prompt_hash`
   - `input_artifacts`
   - `output_artifact`

## Nice-to-Have Enhancements

1. Add Stage 3 reviewer LLM call per ticket and save `review_results.json`.
2. Externalize prompts/config (categories, escalation rules, banned phrases).
3. Add `validate.py` to verify artifact presence, schema validity, stage order, and policy citation constraints.

## Tech Stack

- **Language:** Python 3.11+
- **Project/Dependency management:** `venv` + `pip`
- **LLM provider:** **OpenRouter** (HTTP API)
- **HTTP client:** `httpx`
- **Data modeling/validation:** `pydantic`
- **Deterministic retrieval:** Python standard library token overlap scoring (optional `numpy` if needed)
- **Serialization/logging:** `json`, `jsonlines` pattern, `hashlib`, `datetime`
- **CLI execution:** `python main.py` and optional `python validate.py`

## OpenRouter Integration Notes

- Use OpenRouter for all LLM stages (`triage`, `drafting`, optional `review`).
- Recommended environment variables:
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_MODEL` (for example, `openai/gpt-4o-mini` or another available model)
  - optional: `OPENROUTER_BASE_URL` (defaults to `https://openrouter.ai/api/v1`)
- Log `provider: "openrouter"` and actual model in each `llm_calls.jsonl` record.
- Keep one API call per ticket per stage (no batching for triage/drafting).

## Phased Implementation Plan

## Progress Tracker

- [x] Phase 1: Core Skeleton and Contracts
- [x] Phase 2: Stage 1 Triage
- [x] Phase 3: Deterministic Policy Retrieval
- [x] Phase 4: Stage 2 Drafting
- [ ] Phase 5: Deterministic Checks
- [ ] Phase 6: Final Response Pack
- [ ] Phase 7 (Nice-to-Have): Reviewer + Validator

### Phase 1: Core Skeleton and Contracts (Done)

- Define typed schemas for:
  - ticket
  - policy
  - triage output
  - retrieval output
  - draft output
  - check output
  - final output
  - llm call log record
- Implement pipeline state machine and artifact writer.
- Ensure reproducible JSON output formatting.

### Phase 2: Stage 1 Triage (Done)

- Build one-ticket-at-a-time triage prompt template.
- Include ticket fields, categories, and escalation rules in each call.
- Parse and validate structured JSON output.
- Save `triage.json`.
- Append one `llm_calls.jsonl` entry per triage call.

### Phase 3: Deterministic Policy Retrieval (Done)

- Tokenize ticket text and policy text/tags deterministically.
- Score and rank policies (top 2-3).
- Ensure at least one tone/safety policy is included when relevant.
- Save `retrieval_results.json` with ranking explanation.

### Phase 4: Stage 2 Drafting (Done)

- For each ticket, call LLM using:
  - original ticket
  - ticket triage result
  - retrieved policy snippets only
- Enforce structured JSON output and citation list.
- Save `draft_responses.json`.
- Log each drafting call to `llm_calls.jsonl`.

### Phase 5: Deterministic Checks

- Validate each draft for:
  - missing citations
  - citation outside retrieved set
  - banned promise language
  - empty/too-short reply
  - escalation mismatch with triage
- Save `response_checks.json`.

### Phase 6: Final Response Pack

- Merge triage + retrieval + draft + check outputs.
- Set `final_status`:
  - `needs_human_review` when deterministic checks fail
  - otherwise `ready` (including escalation-safe replies where applicable)
- Save `final_responses.json`.

### Phase 7 (Nice-to-Have): Reviewer + Validator

- Add per-ticket reviewer LLM stage and save `review_results.json`.
- Integrate reviewer result into final review routing.
- Add `validate.py` for evaluator-facing checks.

## Output Artifacts

Required:

- `tickets.json`
- `policy_kb.json`
- `triage.json`
- `retrieval_results.json`
- `draft_responses.json`
- `response_checks.json`
- `final_responses.json`
- `llm_calls.jsonl`
- `README.md`

Optional but recommended:

- `review_results.json`
- `validate.py`

## Validation Checklist

1. Pipeline can regenerate all outputs from clean checkout.
2. Inputs are read from disk at runtime.
3. Triage and drafting are separate per-ticket LLM calls.
4. Retrieval runs before drafting.
5. Draft citations only reference retrieved policies.
6. Deterministic check failures propagate to final status.
7. `llm_calls.jsonl` has one record per ticket-level call with required metadata.
