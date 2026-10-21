"""Bounded public-web fetches with DNS checked at the socket connection boundary."""
import http.client
import ipaddress
import socket
import ssl
from functools import partial
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_FETCH_BYTES = 2_000_000


class UserError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalize_url(value):
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        if parts.port and parts.port not in (80, 443):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if host in ("www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            host = "x.com"
        import re
        if host == "x.com":
            match = re.search(r"/(?:[^/]+|i/web)/status/(\d+)", parts.path)
            if match:
                return f"https://x.com/i/web/status/{match.group(1)}"
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")])
        netloc = f"[{host}]" if ":" in host else host
        return urlunsplit((parts.scheme, netloc, parts.path or "/", query, ""))
    except (ValueError, UnicodeError):
        raise UserError("链接格式不正确：仅支持不含账号密码的 HTTP/HTTPS 标准端口链接。") from None


def public_connect(address, timeout=15, source_address=None, allow_benchmark_proxy=False, **kwargs):
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise UserError("域名未能解析，请检查链接或粘贴全文。")
    for item in infos:
        addr = ipaddress.ip_address(item[4][0].split("%")[0])
        benchmark_proxy = allow_benchmark_proxy and isinstance(addr,ipaddress.IPv4Address) and addr in ipaddress.ip_network('198.18.0.0/15')
        if (not addr.is_global and not benchmark_proxy) or addr.is_multicast:
            if isinstance(addr,ipaddress.IPv4Address) and addr in ipaddress.ip_network('198.18.0.0/15'):
                raise UserError('域名被本机网络代理映射到 198.18/15 测试地址。可粘贴全文；若确认使用 Fake-IP 代理，参照 README 配置采集选项。')
            raise UserError("为保护本机数据，采集器只访问公共互联网地址。")
    last_error = None
    for family, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or UserError("无法连接来源。")


def fetch_public(url, allow_benchmark_proxy=False):
    current = normalize_url(url)
    for _ in range(5):
        parts = urlsplit(current)
        if parts.hostname in ("x.com", "twitter.com"):
            raise UserError("X 链接请使用官方 API 或粘贴全文。")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        conn = cls(parts.hostname, timeout=18)
        conn._create_connection = partial(public_connect,allow_benchmark_proxy=allow_benchmark_proxy)
        try:
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            conn.request("GET", path, headers={"User-Agent": "XSecondBrain/0.1 (personal read-it-later)", "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                target = response.getheader("Location")
                if not target:
                    raise UserError("来源重定向缺少地址。")
                current = normalize_url(urljoin(current, target))
                continue
            if response.status != 200:
                raise UserError(f"来源返回 HTTP {response.status}，请粘贴文章全文。")
            ctype = response.getheader("Content-Type", "").lower()
            if not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
                raise UserError("此来源不是可读取的网页或文本，请粘贴全文。")
            raw = response.read(MAX_FETCH_BYTES + 1)
            if len(raw) > MAX_FETCH_BYTES:
                raise UserError("网页超过 2 MB 采集上限，请粘贴正文。")
            return raw, ctype, current
        except UserError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError):
            raise UserError("来源连接失败或超时；链接已保存，可以稍后重试或补充全文。") from None
        finally:
            conn.close()
    raise UserError("来源重定向次数过多，请粘贴全文。")
