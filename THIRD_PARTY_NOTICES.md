# Third-party notices

X Second Brain's own code, interface, schema, and skill are independently written and released under LICENSE (MIT). No business code, UI assets, logos, or prompts are copied from the five researched reference projects. Their license findings are recorded in docs/RESEARCH.md; inclusion in that research does not make them dependencies.

Direct runtime dependencies:

| Component | License | Purpose |
| --- | --- | --- |
| Python / SQLite | PSF / public domain (SQLite core) | Runtime and persistent local storage |
| FastAPI / Starlette / Pydantic | MIT | HTTP API and validated structures |
| Uvicorn | BSD-3-Clause | ASGI server |
| HTTPX / HTTPcore | BSD-3-Clause | Configured model and official X API clients |
| Trafilatura | Apache-2.0 | Public HTML article extraction |
| python-dotenv | BSD-3-Clause | Server environment configuration |
| NumPy | BSD-3-Clause plus bundled notices | Float32 cosine retrieval |
| cryptography / CFFI / pycparser | Apache-2.0 OR BSD-3-Clause / MIT-0 / BSD-3-Clause | Encrypted credentials on non-Windows platforms; Windows uses system DPAPI |
| FastEmbed | Apache-2.0 | Optional CPU embedding adapter |
| ONNX Runtime | MIT plus bundled notices | Optional local inference |
| BAAI/bge-small-zh-v1.5 | MIT (model card) | Optional downloaded Chinese embedding weights |

The installed, resolved dependency versions and metadata are captured in [docs/dependency-licenses.json](docs/dependency-licenses.json). Original license/notice files supplied by their distributions are copied without modification under [licenses/](licenses/). The snapshot includes test/build dependencies where installed. It is generated from package metadata, not a substitute for reviewing terms when replacing dependencies. SQLite is accessed through Python's standard library, not a separately redistributed SQLite extension.

Optional test tooling: llama.cpp official CPU binaries (MIT), Qwen/Qwen3-4B-GGUF and Qwen/Qwen2.5-1.5B-Instruct-GGUF models (Apache-2.0 per their model repositories; consult the model card for the chosen version) are downloaded only by the explicitly invoked local smoke-test helper into ignored .cache/. They are not included in the source release or required to run the product. Preserve their original bundled licenses if redistributing those binaries or weights. These tools are used for real inference testing, not copied into core code.

Optional FxEmbed public API: the upstream FxEmbed project is MIT-licensed; no upstream business code is vendored. This project's adapter is independently implemented against the documented JSON API. Remote service availability and platform permission are separate from the source license. Enabling it sends the IDs of incomplete captured public posts to api.fxtwitter.com. See docs/FREE_FULLTEXT.md for disclosure and validation limits.

Users retain control of imported text and backups. Source articles retain their original copyrights. Configuring an external language or embedding provider sends selected article text/query context to that provider under that provider's terms; no analytics or telemetry endpoint is added by this application.
