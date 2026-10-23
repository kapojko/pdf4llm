# pdf4llm

CLI utility to convert PDF to properly formatted Markdown, for downstream LLM processing. Main focus are technical documents (electronic datasheets, reference manuals).

# Repo structure

* `src/pdf4llm/` — the package:
  * `cli.py` — Typer CLI entry point (`pdf4llm` command);
  * `convert.py` — PDF → Markdown conversion (pymupdf + ONNX layout models);
  * `config.py` — config file loading (`endpoint`, `api_key`, `llm_sampling`, ...);
  * `prune.py` — Markdown pruning (image/link/heading noise removal);
  * `checks.py` — environment/dependency checks;
  * LLM correction pass, one module per concern (all `llm_*.py`):
    `llm_run.py` (orchestration, `correct_with_llm` entry point),
    `llm_chunk.py` (structure-preserving chunking),
    `llm_classify.py` (technical/general document classification),
    `llm_prompts.py` (prompt templates),
    `llm_client.py` (transport, sampling plumbing, output token cap),
    `llm_protocol.py` (indexed `N|` echo protocol + hinted retry rounds),
    `llm_verify.py` (algorithmic verifier — the safety gate),
    `llm_table.py` (table/cell geometry, TOC detection),
    `llm_salvage.py` (line-level salvage of rejected candidates),
    `llm_batch.py` (cross-chunk batch scheduler: unit registry, kind-separated
    queues, batch packer, global-requeue retries, vocabulary SEND/SKIP filter),
    `llm_prepass.py` (deterministic pre-passes),
    `llm_server.py` (llama-swappy probing, worker pool, interrupt/context errors).
* `tests/` — offline test suite (`test_llm.py` covers the LLM pass, `test_convert.py`/`test_cli_options.py` the rest).
* `scripts/` — one-off experiment & diagnostic scripts (`exp*.py`, `diag_rejections.py`, `probe_new_rules.py`); `scripts/bench/` — local model benchmarks (`bench_llm_local.py`, `probe_quality.py`).
* `examples/` — sample documents (only the small 74HC_HCT74 fixture is committed).
* `out/` — conversion/benchmark outputs, gitignored.

# Precautions

* Initial PDF -> MD processing (before LLM stage) requires ONNX models, and not so fast. Converting 2000-pages document requires 3-4 minutes with CUDA. Don't convert without necessity, use pre-converted MD when testing LLM part.
* LLM processing is not fast. Processing speed on server side is around 90 tps decode, splitted by number of slots. Don't run unnecessary processing. When making test runs, collect all data from the first run (to some temporary file, for example), to avoid second call just to capture full reply.
* Model is configured on server with recommended temperature and sampling parameters. Don't override it on client side without explicit necessity.
* When making test runs, run only short commands (1-2 minutes, 5 minutes max) during usual checks. Longer runs are only with explicit user command.

# Commit rules

* Don't commit without explicit user command.
* When version is changed in the commit, prepend it to the commit message text in square brackets, like "[1.1.0] <commit description>"

