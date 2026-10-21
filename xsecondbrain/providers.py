import json
import hashlib
import logging
import re
import threading
from typing import TypeVar

import httpx
import numpy as np
from pydantic import BaseModel, ValidationError

from .config import Settings
from .security import UserError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_output = None

    def structured(self, system: str, user: str, schema: type[T], evidence_chunks=None, property_enums=None) -> T:
        if not self.settings.llm_enabled:
            raise UserError("未配置可用的阅读模型。请检查 Codex CLI 登录或 LLM_MODEL/LLM_API_KEY。原文已保存。", 503)
        json_schema = schema.model_json_schema()
        for field,values in (property_enums or {}).items():
            if field in json_schema.get('properties', {}):
                json_schema['properties'][field]['enum'] = values
        if evidence_chunks and 'Evidence' in json_schema.get('$defs', {}):
            # Bind each possible quote to the chunk it actually occurs in. Schema-capable
            # providers can enforce this at decoding time; all outputs are still checked.
            options = []
            for chunk in evidence_chunks:
                quotes = []
                for part in re.split(r'(?<=[。！？.!?；;])\s*|\n+', chunk['text']):
                    part = part.strip()
                    if len(part) >= 8:
                        quotes.extend(part[i:i+400] for i in range(0,len(part),400) if len(part[i:i+400]) >= 8)
                if not quotes:
                    quotes = [chunk['text']]
                options.append({'type':'object','properties':{'chunk_id':{'type':'string','const':chunk['id']},'quote':{'type':'string','enum':list(dict.fromkeys(quotes))}},'required':['chunk_id','quote'],'additionalProperties':False})
            json_schema['$defs']['Evidence'] = {'anyOf':options}
            system += '\n引用只从 schema 中列出的原文句子选取，保留对应 chunk_id；不要重新措辞引文。'
        if self.settings.llm_provider == 'codex':
            from .codex_provider import read_structured
            raw = read_structured(self.settings, system, user, json_schema)
            try:
                parsed = schema.model_validate_json(raw)
            except (ValueError, ValidationError):
                raise UserError('后台 Codex 输出未通过结构验证，未作为知识保存。',502) from None
            self.last_output = parsed.model_dump()
            return parsed
        instructions = system + '\n只返回完整的 JSON 对象，不要用 Markdown 代码块。'
        if not self.settings.llm_json_schema:
            instructions += '\n符合以下 JSON Schema：\n' + json.dumps(json_schema, ensure_ascii=False)
        messages = [{"role": "system", "content": instructions}, {"role": "user", "content": user}]
        with httpx.Client(timeout=self.settings.llm_timeout, follow_redirects=False) as client:
            for attempt in range(2):
                body = {"model": self.settings.llm_model, "messages": messages, "max_tokens": self.settings.llm_max_tokens}
                if self.settings.llm_json_schema:
                    body['response_format'] = {'type':'json_schema', 'json_schema':{'name':schema.__name__, 'schema':json_schema, 'strict':False}}
                elif self.settings.llm_json_mode:
                    body["response_format"] = {"type": "json_object"}
                try:
                    res = client.post(self.settings.llm_base_url.rstrip('/') + '/chat/completions', headers={"Authorization": f"Bearer {self.settings.llm_api_key}"}, json=body)
                except httpx.TimeoutException:
                    raise UserError("模型请求超时；原文已保留，请重试或切换模型。", 504) from None
                except httpx.HTTPError:
                    raise UserError("无法连接模型服务，请检查服务地址及网络。", 503) from None
                if res.status_code != 200:
                    # Never expose provider response bodies; they can reflect headers or secrets.
                    raise UserError(f"模型服务返回 HTTP {res.status_code}，请检查密钥、模型、余额及 JSON 模式兼容性。", 502)
                try:
                    payload = res.json()
                    if payload['choices'][0].get('finish_reason') == 'length':
                        raise UserError('模型输出达到 token 上限，未保存不完整结果。请提高 LLM_MAX_TOKENS 或使用更强的模型。',502)
                    raw = payload['choices'][0]['message']['content']
                    if not isinstance(raw, str):
                        raise ValueError()
                    clean = raw.strip()
                    if clean.startswith('```'):
                        clean = clean.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                    parsed = schema.model_validate_json(clean)
                    self.last_output = parsed.model_dump()
                    return parsed
                except (KeyError, IndexError, TypeError, ValueError, ValidationError):
                    if attempt:
                        raise UserError("模型输出不符合结构要求，未写入伪造摘要。请重试或使用支持 JSON 的模型。", 502) from None
                    messages.extend([{"role": "assistant", "content": raw if 'raw' in locals() and isinstance(raw, str) else "{}"}, {"role": "user", "content": "上一次输出无法解析或不符合 schema。请修正为完整且有效的 JSON，保留真实证据，不要编造。"}])
        raise UserError("模型没有返回有效结果。", 502)


class Embeddings:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._lock = threading.Lock()
        self.error = ""

    @property
    def signature(self):
        # Endpoint also matters: identical model names at different providers may be incompatible.
        endpoint = hashlib.sha256(self.settings.embedding_base_url.rstrip('/').encode()).hexdigest()[:16] if self.settings.embedding_provider == 'api' else 'fastembed'
        return f"{self.settings.embedding_provider}:{self.settings.embedding_model}:{endpoint}"

    def encode(self, texts, query=False):
        if not texts:
            return []
        provider = self.settings.embedding_provider
        if provider == "none":
            raise UserError("语义检索已关闭，当前使用全文检索。")
        try:
            if provider == "local":
                with self._lock:
                    if self._model is None:
                        from fastembed import TextEmbedding
                        self._model = TextEmbedding(model_name=self.settings.embedding_model, cache_dir=str(self.settings.data_dir / "models"), threads=2)
                    iterator = self._model.query_embed(texts) if query else self._model.passage_embed(texts)
                    vectors = list(iterator)
            else:
                if not self.settings.embedding_api_key:
                    raise UserError("未配置 EMBEDDING_API_KEY，语义检索暂不可用。")
                vectors = []
                with httpx.Client(timeout=60, follow_redirects=False) as client:
                    for offset in range(0, len(texts), 32):
                        batch = texts[offset:offset + 32]
                        res = client.post(self.settings.embedding_base_url.rstrip('/') + '/embeddings', headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"}, json={"model": self.settings.embedding_model, "input": batch})
                        if res.status_code != 200:
                            raise UserError(f"向量服务返回 HTTP {res.status_code}，已保留全文检索。")
                        data = sorted(res.json()['data'], key=lambda x: x['index'])
                        if len(data) != len(batch) or [d['index'] for d in data] != list(range(len(batch))):
                            raise UserError("向量服务返回条目不完整。")
                        vectors.extend(d['embedding'] for d in data)
            array = np.asarray(vectors, dtype=np.float32)
            if array.ndim != 2 or len(array) != len(texts) or not np.isfinite(array).all():
                raise UserError("模型返回无效向量，当前使用全文检索。")
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise UserError("向量长度为零。")
            self.error = ""
            return array / norms
        except UserError as exc:
            self.error = str(exc)
            raise
        except Exception as exc:
            log.warning("embedding unavailable (%s)", type(exc).__name__)
            self.error = "本地语义模型尚未就绪。请安装 semantic 依赖、检查模型下载网络并重建索引；当前仍可全文检索。"
            raise UserError(self.error) from None
