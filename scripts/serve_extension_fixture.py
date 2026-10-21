"""Temporary loopback-only fixture page. No private files or knowledge DB are served."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES={'/':ROOT/'tests/fixtures/browser-capture.html',
       '/clipper-core.js':ROOT/'xsecondbrain/browser_extension/clipper-core.js',
       '/content.js':ROOT/'xsecondbrain/browser_extension/content.js'}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=FILES.get(self.path)
        if path is None:
            self.send_error(404);return
        body=path.read_bytes();self.send_response(200)
        self.send_header('Content-Type','text/javascript; charset=utf-8' if path.suffix=='.js' else 'text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass


if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',8790),Handler).serve_forever()
