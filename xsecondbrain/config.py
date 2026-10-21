from dataclasses import dataclass
from pathlib import Path
import os
import shutil

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "data"
    host: str = "127.0.0.1"
    port: int = 8787
    app_token: str = ""
    headless: bool = True
    llm_provider: str = "api"
    codex_binary: str = "codex"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: float = 120
    llm_json_mode: bool = True
    llm_json_schema: bool = False
    llm_max_tokens: int = 6500
    knowledge_workers: int = 1
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    semantic_threshold: float = 0.40
    x_bearer_token: str = ""
    x_fetch_threads: bool = False
    x_thread_max_pages: int = 2
    x_client_id: str = ""
    x_client_secret: str = ""
    x_redirect_uri: str = ""
    fetch_allow_benchmark_proxy: bool = False
    x_public_fulltext_provider: str = 'none'

    @property
    def llm_enabled(self):
        if self.llm_provider == 'codex':
            return bool(shutil.which(self.codex_binary))
        return bool(self.llm_model and self.llm_api_key)

    @property
    def model_label(self):
        return 'Codex CLI · 默认模型' if self.llm_provider == 'codex' else self.llm_model

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        values = {}
        for name, field in cls.__dataclass_fields__.items():
            raw = os.getenv(name.upper())
            if raw is None:
                continue
            default = field.default
            if isinstance(default, bool):
                values[name] = raw.lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                values[name] = int(raw)
            elif isinstance(default, float):
                values[name] = float(raw)
            elif isinstance(default, Path):
                path = Path(raw).expanduser()
                values[name] = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
            else:
                values[name] = raw.strip()
        settings = cls(**values)
        if settings.embedding_provider not in ("none", "local", "api"):
            raise ValueError("EMBEDDING_PROVIDER must be none, local or api")
        if settings.llm_provider not in ('api', 'codex'):
            raise ValueError('LLM_PROVIDER must be api or codex')
        if settings.x_public_fulltext_provider not in ('none', 'fxembed'):
            raise ValueError('X_PUBLIC_FULLTEXT_PROVIDER must be none or fxembed')
        if not 1 <= settings.knowledge_workers <= 3:
            raise ValueError('KNOWLEDGE_WORKERS must be between 1 and 3')
        if not 0 <= settings.semantic_threshold <= 1:
            raise ValueError("SEMANTIC_THRESHOLD must be between 0 and 1")
        if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.app_token:
            raise ValueError("非本机监听必须设置 APP_TOKEN。")
        return settings
