"""
Non-blocking HTTPS GET client using raw sockets and a state machine.
This is the core innovation of the refactored architecture:
every network operation is split into small steps that return immediately
when data isn't ready (EAGAIN), so the main loop never blocks on I/O.

Usage:
    client = HTTPClient(pool, ssl_context)
    client.get("https://api.example.com/data")
    while not client.done:
        client.tick()          # call every main loop iteration
    if client.status == 200:
        data = client.json()   # parsed JSON
    client.reset()             # reuse for next request

States (internal):
    IDLE=0  TCP_CONNECT=1  SSL_HANDSHAKE=2  SEND_REQUEST=3
    RECV_STATUS=4  RECV_HEADERS=5  RECV_BODY=6
    COMPLETE=7  ERROR=8  TIMEOUT=9
"""
import time
import gc
import ssl as _ssl_module
import json
from settings import HTTP_TIMEOUT

# ── CPython / CircuitPython compat ────────────────────────────────
# CircuitPython's ssl module doesn't have SSLWantReadError etc.
# Build exception tuple dynamically so AttributeError is avoided at import time.
_SSL_RETRY_EXC = ()
_SSL_EOF_EXC = ()
try:
    _SSL_RETRY_EXC = (_ssl_module.SSLWantReadError, _ssl_module.SSLWantWriteError)
    _SSL_EOF_EXC   = (_ssl_module.SSLEOFError, _ssl_module.SSLSyscallError)
except AttributeError:
    pass  # CircuitPython — OSError with EAGAIN covers these


# ── States ─────────────────────────────────────────────────────────
(
    S_IDLE,         # 0 — waiting for get() call
    S_TCP_CONNECT,  # 1 — TCP socket connecting
    S_SSL_HANDSHAKE,# 2 — TLS handshake in progress
    S_SEND_REQUEST, # 3 — writing HTTP request bytes
    S_RECV_STATUS,  # 4 — reading HTTP status line
    S_RECV_HEADERS, # 5 — reading response headers
    S_RECV_BODY,    # 6 — reading response body
    S_COMPLETE,     # 7 — request finished successfully
    S_ERROR,        # 8 — request failed
    S_TIMEOUT,      # 9 — request exceeded deadline
) = range(10)

_STATE_NAMES = [
    "IDLE", "TCP_CONNECT", "SSL_HANDSHAKE", "SEND_REQUEST",
    "RECV_STATUS", "RECV_HEADERS", "RECV_BODY",
    "COMPLETE", "ERROR", "TIMEOUT",
]


class HTTPClient:
    def __init__(self, pool, ssl_context=None):
        self._pool = pool
        self._ssl_context = ssl_context

        # Public result fields
        self.status_code = 0
        self.body_bytes = None      # raw response body
        self.error_msg = None       # error string if ERROR/TIMEOUT

        # Internal state
        self._state = S_IDLE
        self._sock = None
        self._ssl_sock = None

        # Request parameters
        self._host = ""
        self._port = 443
        self._path = "/"

        # Timing
        self._start_time = 0.0
        self._deadline = 0.0

        # Send buffer
        self._req_bytes = b""
        self._req_view = None
        self._sent = 0

        # Receive buffer — pre-allocated 1024-byte bytearray, reused
        self._recv_buf = bytearray(1024)

        # Body accumulator
        self._body_buf = bytearray()

        # Header parsing state
        self._header_bytes = bytearray()
        self._content_length = -1  # -1 = unknown, use EOF
        self._is_chunked = False   # True if Transfer-Encoding: chunked
        self._body_received = 0
        self._headers_complete = False
        self._status_line = ""

    # ── Public API ─────────────────────────────────────────────────
    @property
    def done(self):
        """True when the request has finished (success, error, or timeout)."""
        return self._state in (S_COMPLETE, S_ERROR, S_TIMEOUT)

    @property
    def state_name(self):
        return _STATE_NAMES[self._state]

    def get(self, url, timeout=HTTP_TIMEOUT):
        """
        Start a non-blocking HTTPS GET request.
        Returns immediately. Call tick() repeatedly until .done is True.
        """
        if self._state not in (S_IDLE, S_COMPLETE, S_ERROR, S_TIMEOUT):
            raise RuntimeError(f"HTTPClient busy: state={self.state_name}")

        # Reset
        self.status_code = 0
        self.body_bytes = None
        self.error_msg = None
        self._body_buf = bytearray()
        self._header_bytes = bytearray()
        self._content_length = -1
        self._is_chunked = False
        self._body_received = 0
        self._headers_complete = False
        self._status_line = ""
        self._sent = 0

        # Parse URL
        self._parse_url(url)

        # Build HTTP request
        self._req_bytes = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}\r\n"
            "User-Agent: MatrixPortal-S3/1.0\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()
        self._req_view = memoryview(self._req_bytes)

        # Timing
        self._start_time = time.monotonic()
        self._deadline = self._start_time + timeout

        # Start state machine
        self._state = S_TCP_CONNECT
        self._cleanup_socket()

    def json(self):
        """Parse response body as JSON. Call only when .done and status==200."""
        if self.body_bytes is None:
            return None
        gc.collect()
        try:
            result = json.loads(self.body_bytes)
        except Exception:
            result = None
        gc.collect()
        return result

    def reset(self):
        """Reset to idle for reuse."""
        self._cleanup_socket()
        self.status_code = 0
        self.body_bytes = None
        self.error_msg = None
        self._state = S_IDLE

    # ── State machine tick ─────────────────────────────────────────
    def tick(self):
        """Advance the state machine. Call frequently (every main loop iteration).
        Returns quickly — does NOT block on I/O."""
        if self._state in (S_IDLE, S_COMPLETE, S_ERROR, S_TIMEOUT):
            return

        # Check deadline
        if time.monotonic() > self._deadline:
            self._set_error("Timeout", S_TIMEOUT)
            return

        try:
            if self._state == S_TCP_CONNECT:
                self._tick_tcp_connect()
            elif self._state == S_SSL_HANDSHAKE:
                self._tick_ssl_handshake()
            elif self._state == S_SEND_REQUEST:
                self._tick_send()
            elif self._state == S_RECV_STATUS:
                self._tick_recv_status()
            elif self._state == S_RECV_HEADERS:
                self._tick_recv_headers()
            elif self._state == S_RECV_BODY:
                self._tick_recv_body()
        except _SSL_RETRY_EXC:
            pass  # CPython non-blocking SSL: try again next tick
        except _SSL_EOF_EXC:
            # SSL connection closed or syscall error
            self._finish_or_error()
        except OSError as e:
            err_str = str(e)
            # EAGAIN / EWOULDBLOCK / EINPROGRESS — normal for non-blocking
            if any(x in err_str for x in (
                "EAGAIN", "would block", "again",
                "in progress", "EINPROGRESS", "EWOULDBLOCK",
                "The operation did not complete",  # CPython SSL non-blocking
            )):
                pass  # Not an error — will retry on next tick
            else:
                self._set_error(f"OSError: {err_str}", S_ERROR)
        except Exception as e:
            self._set_error(str(e), S_ERROR)

    # ── URL parsing ────────────────────────────────────────────────
    @staticmethod
    def _parse_url_impl(url):
        """Extract host, port, path from a URL string."""
        # Remove protocol prefix
        if url.startswith("https://"):
            url = url[8:]
            default_port = 443
        elif url.startswith("http://"):
            url = url[7:]
            default_port = 80
        else:
            default_port = 443

        # Split host and path
        if "/" in url:
            host_part, path = url.split("/", 1)
            path = "/" + path
        else:
            host_part = url
            path = "/"

        # Split host and port
        if ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_part
            port = default_port

        return host, port, path

    def _parse_url(self, url):
        self._host, self._port, self._path = self._parse_url_impl(url)

    # ── Per-state tick implementations ─────────────────────────────
    def _tick_tcp_connect(self):
        """Create socket and connect with short timeout — then immediately
        transition to SSL handshake. On ESP32-S3 TCP connects in <100ms."""
        try:
            self._sock = self._pool.socket(
                self._pool.AF_INET, self._pool.SOCK_STREAM)
            self._sock.settimeout(5.0)  # 5s timeout for connect
            self._sock.connect((self._host, self._port))
            # Connected — proceed to SSL
            self._state = S_SSL_HANDSHAKE
        except OSError as e:
            err = str(e)
            # On some platforms, non-blocking connect raises EINPROGRESS
            if "in progress" in err or "EINPROGRESS" in err:
                self._state = S_SSL_HANDSHAKE  # Proceed anyway
            else:
                self._set_error(f"TCP connect: {err}", S_ERROR)

    def _tick_ssl_handshake(self):
        """Perform TLS handshake. This may block briefly (~200-500ms)."""
        try:
            # SSL handshake needs a blocking socket to complete.
            # Temporarily set blocking with a short timeout.
            self._sock.setblocking(True)
            self._sock.settimeout(5.0)  # 5 second handshake timeout
            self._ssl_sock = self._ssl_context.wrap_socket(
                self._sock, server_hostname=self._host
            )
            # Success — switch to non-blocking for data transfer
            self._ssl_sock.setblocking(False)
            self._state = S_SEND_REQUEST
        except OSError as e:
            err = str(e)
            if "timeout" in err.lower() or "timed out" in err.lower():
                self._set_error("SSL handshake timeout", S_TIMEOUT)
            else:
                self._set_error(f"SSL error: {err}", S_ERROR)
        except Exception as e:
            self._set_error(f"SSL error: {e}", S_ERROR)

    def _tick_send(self):
        """Write HTTP request bytes to the SSL socket. Non-blocking."""
        try:
            sent = self._ssl_sock.send(self._req_view[self._sent:])
            self._sent += sent
        except OSError as e:
            err = str(e)
            if "would block" in err or "EAGAIN" in err:
                return  # Try again next tick
            raise

        if self._sent >= len(self._req_bytes):
            # All bytes sent — start receiving
            self._state = S_RECV_STATUS

    def _tick_recv_status(self):
        """Read the HTTP status line (ends with \r\n)."""
        self._append_recv_to_header()
        if b"\r\n" in self._header_bytes:
            # Extract status line
            idx = self._header_bytes.find(b"\r\n")
            self._status_line = self._header_bytes[:idx].decode("utf-8", "ignore")
            # Remove status line from header buffer
            self._header_bytes = self._header_bytes[idx + 2:]
            # Parse status code
            parts = self._status_line.split(" ")
            if len(parts) >= 2:
                try:
                    self.status_code = int(parts[1])
                except ValueError:
                    self.status_code = 0
            self._state = S_RECV_HEADERS

    def _tick_recv_headers(self):
        """Read HTTP headers (until \r\n\r\n)."""
        self._append_recv_to_header()
        if b"\r\n\r\n" in self._header_bytes:
            # Headers complete — parse Content-Length
            idx = self._header_bytes.find(b"\r\n\r\n")
            headers_block = self._header_bytes[:idx].decode("utf-8", "ignore")
            # Any bytes after \r\n\r\n are body bytes
            remaining = self._header_bytes[idx + 4:]
            self._header_bytes = bytearray()

            # Parse Content-Length and Transfer-Encoding from headers
            self._content_length = -1
            self._is_chunked = False
            for line in headers_block.split("\r\n"):
                lower = line.lower()
                if lower.startswith("content-length:"):
                    try:
                        self._content_length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif lower.startswith("transfer-encoding:") and "chunked" in lower:
                    self._is_chunked = True

            # If we have remaining bytes from the body, add them
            if remaining:
                self._body_buf.extend(remaining)
                self._body_received += len(remaining)

            self._headers_complete = True
            self._state = S_RECV_BODY
            # Check if we already have all the body
            self._check_body_complete()

    def _tick_recv_body(self):
        """Read response body bytes."""
        if not self._headers_complete:
            self._state = S_RECV_HEADERS
            return

        try:
            n = self._ssl_sock.recv_into(self._recv_buf)
            if n > 0:
                self._body_buf.extend(self._recv_buf[:n])
                self._body_received += n
            elif n == 0:
                # EOF — connection closed
                self._finish_request()
                return
        except OSError as e:
            err = str(e)
            if "would block" in err or "EAGAIN" in err:
                pass  # No data available, try again next tick
            else:
                raise

        # Check if chunked body is complete.
        # Final-chunk = "0" CRLF, optionally followed by trailers, ending with CRLF.
        if self._is_chunked:
            zero_marker = b"\r\n0\r\n"
            zidx = self._body_buf.rfind(zero_marker)
            if zidx >= 0:
                after_zero = self._body_buf[zidx + len(zero_marker):]
                if after_zero.endswith(b"\r\n"):
                    self._finish_request()
                    return

        self._check_body_complete()

    # ── Helpers ────────────────────────────────────────────────────
    def _append_recv_to_header(self):
        """Try to read bytes into header buffer. Non-blocking."""
        try:
            n = self._ssl_sock.recv_into(self._recv_buf)
            if n > 0:
                self._header_bytes.extend(self._recv_buf[:n])
        except OSError as e:
            err = str(e)
            if "would block" in err or "EAGAIN" in err:
                return  # No data yet
            raise

    def _check_body_complete(self):
        """Check if we've received all body bytes."""
        if self._content_length >= 0:
            if self._body_received >= self._content_length:
                self._finish_request()
        # If no Content-Length, we wait for EOF (recv returns 0)

    def _finish_request(self):
        """Mark request as complete and store results. Dechunks if needed."""
        raw = bytes(self._body_buf)
        if self._is_chunked:
            raw = self._dechunk(raw)
        self.body_bytes = raw
        self._state = S_COMPLETE
        self._close_sockets()

    @staticmethod
    def _dechunk(data):
        """Decode HTTP chunked transfer encoding. Returns dechunked bytes.
        Handles chunk extensions (RFC 7230 §4.1.1: chunk-ext = \";\" token)."""
        result = bytearray()
        pos = 0
        while pos < len(data):
            # Find chunk size line
            end = data.find(b"\r\n", pos)
            if end < 0:
                break
            # Strip chunk extension (e.g. \"7;foo=bar\" → \"7\")
            size_str = data[pos:end]
            semi = size_str.find(b";")
            if semi >= 0:
                size_str = size_str[:semi]
            try:
                chunk_size = int(size_str, 16)
            except ValueError:
                break
            pos = end + 2
            if chunk_size == 0:
                break  # Final chunk (trailers after this are ignored)
            # Extract chunk data
            if pos + chunk_size <= len(data):
                result.extend(data[pos:pos + chunk_size])
                pos += chunk_size + 2  # skip \r\n after data
            else:
                break
        return bytes(result)

    def _finish_or_error(self):
        """Handle SSL EOF or syscall error — finish if we have body data."""
        if len(self._body_buf) > 0 and self._headers_complete:
            self._finish_request()
        else:
            self._set_error("SSL connection closed unexpectedly", S_ERROR)

    def _set_error(self, msg, state):
        """Transition to an error state."""
        self.error_msg = msg
        self._state = state
        self._close_sockets()
        if state == S_ERROR or state == S_TIMEOUT:
            print(f"HTTPClient {state}: {msg}")

    def _close_sockets(self):
        """Close both SSL and raw sockets."""
        for sock in (self._ssl_sock, self._sock):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self._ssl_sock = None
        self._sock = None

    def _cleanup_socket(self):
        """Close any existing sockets and reset socket state."""
        self._close_sockets()
        self._header_bytes = bytearray()
        self._body_buf = bytearray()
        self._content_length = -1
        self._is_chunked = False
        self._body_received = 0
        self._headers_complete = False
