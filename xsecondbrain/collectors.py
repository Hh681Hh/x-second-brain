from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import trafilatura

from .config import Settings
from .security import UserError, fetch_public
from .models import MAX_CONTENT


@dataclass
class Collected:
    content: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    note: str = ""
    source_kind: str = "article"


class BookmarkSyncAdapter(Protocol):
    """Extension contract: only official, user-authorized OAuth integrations."""
    def fetch_page(self, user_access_token: str, cursor: str | None = None) -> tuple[list[dict], str | None]: ...


def collect(url: str, settings: Settings) -> Collected:
    if urlsplit(url).hostname == "x.com":
        return collect_x(url, settings)
    raw, ctype, _ = fetch_public(url,allow_benchmark_proxy=settings.fetch_allow_benchmark_proxy)
    if "text/plain" in ctype:
        content = raw.decode("utf-8", errors="replace").strip()
        result = Collected(content, title=content.splitlines()[0][:180], note="来自公开文本页面；请确认正文完整。")
    else:
        doc = trafilatura.bare_extraction(raw, with_metadata=True, include_links=False, include_comments=False, include_tables=True)
        if not doc:
            raise UserError("网页未能提取正文，可能依赖登录或脚本。请补充全文。")
        result = Collected(doc.text or "", doc.title or "", doc.author or "", doc.date or "", "从公开网页提取正文；未绕过登录、付费墙或验证。")
    if len(result.content.strip()) < 40:
        raise UserError("只能取得短预览，未作为全文处理。请粘贴正文。")
    if len(result.content) > MAX_CONTENT:
        raise UserError("正文超过 12 万字符上限，请分篇导入；系统未截断冒充全文。")
    return result


def x_request(client, path, params):
    try:
        response = client.get(f"https://api.x.com/2/{path}", params=params)
    except httpx.HTTPError:
        raise UserError("X 官方接口连接失败，请稍后重试或粘贴全文。") from None
    if response.status_code != 200:
        explanations = {401: "官方令牌无效或已过期", 402: "需要 API 额度", 403: "应用权限、额度或帖子访问受限", 404: "帖子不存在或不可访问", 429: "已达到速率限制"}
        raise UserError(f"X 返回 HTTP {response.status_code}：{explanations.get(response.status_code, '官方接口暂不可用')}。链接已保存，请补充全文。")
    try:
        return response.json()
    except ValueError:
        raise UserError("X 官方接口返回了无效数据。") from None


def post_text(post):
    return ((post.get("article") or {}).get("plain_text") or (post.get("note_tweet") or {}).get("text") or (post.get("note_post") or {}).get("text") or post.get("text") or "").strip()


def collect_x(url: str, settings: Settings) -> Collected:
    if not settings.x_bearer_token:
        raise UserError("X 全文采集需要官方 API 令牌；也可以直接粘贴长文或完整 Thread。无需提供 X 密码或 Cookie。")
    match = re.search(r"/status/(\d+)", url)
    if not match:
        raise UserError("请提供包含 /status/ 的 X 帖子链接；Article 页面请粘贴全文并保留原链接。")
    with httpx.Client(timeout=25, headers={"Authorization": f"Bearer {settings.x_bearer_token}"}, follow_redirects=False) as client:
        # Request Article separately: some X responses omit it when note_tweet is requested together.
        payload = x_request(client, f"tweets/{match[1]}", {"tweet.fields": "created_at,author_id,conversation_id,referenced_tweets,article", "expansions": "author_id", "user.fields": "name,username"})
        post = payload.get("data")
        if not post:
            raise UserError("X 未返回帖子正文，请补充全文。")
        if not (post.get("article") or {}).get("plain_text"):
            extended = x_request(client, f"tweets/{match[1]}", {"tweet.fields": "note_tweet"})
            post["note_tweet"] = (extended.get("data") or {}).get("note_tweet")
        text = post_text(post)
        if (post.get("article") and not post["article"].get("plain_text")) or len(text) < 20 or re.fullmatch(r"https?://\S+", text):
            raise UserError("X 只返回 Article 元数据或短预览，未获取全文。请粘贴完整正文。")
        users = payload.get("includes", {}).get("users", [])
        author = next((f"{u['name']} (@{u['username']})" for u in users if u['id'] == post.get('author_id')), "")
        notes = ["通过 X 官方 API 读取；未抓取图片中的文字及引用帖全文。"]
        kind = "article"
        if settings.x_fetch_threads and post.get("conversation_id") and post.get("author_id"):
            items = {post["id"]: post}
            cursor = None
            try:
                for _ in range(max(1, min(settings.x_thread_max_pages, 5))):
                    params = {"query": f"conversation_id:{post['conversation_id']} from:{post['author_id']} -is:retweet", "tweet.fields": "created_at,note_tweet,referenced_tweets", "max_results": 100}
                    if cursor:
                        params["next_token"] = cursor
                    page = x_request(client, "tweets/search/recent", params)
                    items.update({p['id']: p for p in page.get('data', [])})
                    cursor = page.get('meta', {}).get('next_token')
                    if not cursor:
                        break
                ordered = sorted(items.values(), key=lambda p: int(p['id']))
                text = "\n\n".join(f"[帖子 {p['id']}]\n{post_text(p)}" for p in ordered)
                notes.append(f"已取回同作者 conversation 的 {len(ordered)} 帖；recent search 有时间窗口、分页上限，可能包含旁支回复，不保证完整 Thread。请核对或手工补全。")
                kind = "thread"
            except UserError as exc:
                notes.append(f"Thread 补全失败，仅保留本帖：{exc}")
        elif not (post.get("article") or {}).get("plain_text"):
            notes.append("仅读取此帖，尚未补全 Thread；如内容属于帖子串，请粘贴完整串。")
        if len(text) > MAX_CONTENT:
            raise UserError("Thread 超过 12 万字符，请分篇粘贴导入。")
        return Collected(text, (post.get('article') or {}).get('title') or text.splitlines()[0][:120], author, post.get('created_at', ''), " ".join(notes), kind)
