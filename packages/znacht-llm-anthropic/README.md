# znacht-llm-anthropic

The default `PlannerProvider`: Claude proposes the week and extracts structure from documents. It is never trusted on quantities, prices or rules; the core's checker validates every plan and the household confirms every extraction.

- Model: `claude-opus-5-5` by default (`ZNACHT_ANTHROPIC_MODEL` to change). Thinking is adaptive (the model's default); depth is set with `ZNACHT_ANTHROPIC_EFFORT` (`low`, `medium`, `high`), default `medium`.
- Structured outputs: every call uses the SDK's `parse` with a pydantic schema from `znacht.planner.schemas`, so the response is validated before the core sees it.
- Refusal fallback is on by default (`fallbacks="default"`): if a safety classifier declines, the API re-runs the request on a fallback model inside the same call. Set `ZNACHT_ANTHROPIC_FALLBACKS=off` to disable.
- Credentials: `ANTHROPIC_API_KEY` in the environment (or an `ant auth login` profile). Nothing is written to disk.

Documents: PDFs go in as base64 document blocks, images as base64 image blocks, text as text. The recorded tests use a fake client; a live run needs the key.
