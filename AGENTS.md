# pdf4llm

CLI utility to convert PDF to properly formatted Markdown, for downstream LLM processing. Main focus are technical documents (electronic datasheets, reference manuals).

# Repo structure

TBD

# Precautions

* Initial PDF -> MD processing (before LLM stage) requires ONNX models, and not so fast. Converting 2000-pages document requires 3-4 minutes with CUDA. Don't convert without necessity, use pre-converted MD when testing LLM part.
* LLM processing is not fast. Processing speed on server side is around 90 tps decode, splitted by number of slots. Don't run unnecessary processing. When making test runs, collect all data from the first run (to some temporary file, for example), to avoid second call just to capture full reply.
* Model is configured on server with recommended temperature and sampling parameters. Don't override it on client side without explicit necessity.
* When making test runs, run only short commands (1-2 minutes, 5 minutes max) during usual checks. Longer runs are only with explicit user command.

# Commit rules

* Don't commit without explicit user command.
* When version is changed in the commit, prepend it to the commit message text in square brackets, like "[1.1.0] <commit description>"

