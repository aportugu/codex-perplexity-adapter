"""Local delayed SSE upstream used for packaged-app streaming smoke tests."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for delta in ("first", "second"):
            event = {"type": "response.output_text.delta", "delta": delta}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.5)
        self.close_connection = True

    def log_message(self, format, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", 4020), Handler).serve_forever()
