"""
Non-blocking HTTP control server.
Serves a web page for mode switching and reboot.
Already non-blocking in the original — extracted with minor interface changes.
Uses mode_manager.set() instead of returning a new mode value.
"""
import wifi
from settings import MODE_NAMES


HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <title>LED Board</title>
  <style>
    body {{ font-family:sans-serif; background:#111; color:#eee;
            display:flex; flex-direction:column; align-items:center;
            padding:2rem; gap:1rem; }}
    h2   {{ margin:4rem 0 1rem; }}
    .btn {{ width:220px; padding:1rem; font-size:1.1rem; border:none;
            border-radius:12px; cursor:pointer; }}
    .active   {{ background:#6DBCDB; color:#fff; }}
    .inactive {{ background:#333;    color:#aaa; }}
    .reboot   {{ position:fixed; top:1rem; left:1rem; width:auto;
                 padding:0.5rem 1rem; font-size:0.9rem; background:#FC4349;
                 color:#fff; border:none; border-radius:8px; cursor:pointer; }}
    #status {{ font-size:.9rem; color:#aaa; }}
  </style>
</head>
<body>
  <button class="reboot" onclick="reboot()">Reboot</button>
  <h2>LED Board Control</h2>
  <button class="btn {cls0}" onclick="sw(0)">S-Bahn Info</button>
  <button class="btn {cls1}" onclick="sw(1)">T-Rex</button>
  <p id="status"></p>
  <script>
    function sw(m){{
      fetch('/set?mode='+m)
        .then(r=>r.text())
        .then(t=>{{ document.getElementById('status').textContent=t;
                    document.querySelectorAll('.btn').forEach((b,i)=>{{
                      b.className='btn '+(i==m?'active':'inactive');
                    }});
                    if(m==1){{ window.location.href='/game'; }} }});
    }}
    function reboot(){{
      document.getElementById('status').textContent='Done';
      fetch('/restart').then(()=>{{}}).catch(()=>{{}});
    }}
  </script>
</body>
</html>"""


GAME_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <title>T-Rex</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      font-family:sans-serif; background:#111; color:#eee;
      display:flex; flex-direction:column;
      align-items:center; justify-content:center;
      height:100vh; height:100dvh; overflow:hidden;
      touch-action:manipulation; -webkit-tap-highlight-color:transparent;
      user-select:none; -webkit-user-select:none;
    }
    .back-btn {
      position:fixed; top:1rem; left:1rem; width:auto;
      padding:0.5rem 1rem; font-size:0.9rem;
      background:#6DBCDB; color:#fff; border:none;
      border-radius:8px; cursor:pointer; z-index:10;
      text-decoration:none;
    }
    .jump-btn {
      width:220px; height:220px; border-radius:12px;
      background:#6DBCDB; color:#fff;
      border:none; font-size:2rem;
      font-weight:bold; cursor:pointer;
      transition:transform 0.05s;
    }
    .jump-btn:active { transform:scale(0.95); background:#5AA8C7; }
    .hint { color:#555; font-size:0.85rem; margin-top:2rem; }
  </style>
</head>
<body>
  <a class="back-btn" href="javascript:goBack()">Back</a>
  <button class="jump-btn" id="jumpBtn">JUMP</button>
  <p class="hint">Tap the button to jump</p>
  <script>
    const btn = document.getElementById('jumpBtn');
    function doJump() {
      fetch('/jump').catch(function(){});
    }
    btn.addEventListener('touchstart', function(e){
      e.preventDefault(); doJump();
    });
    btn.addEventListener('mousedown', function(e){
      e.preventDefault(); doJump();
    });
    function goBack() {
      fetch('/set?mode=0').then(function(){
        window.location.href='/';
      });
    }
  </script>
</body>
</html>"""


class WebServer:
    def __init__(self, pool, mode_manager, dino_game=None, port=80):
        self._mode_mgr = mode_manager
        self._dino_game = dino_game
        self._server = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        self._server.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        self._server.bind(("0.0.0.0", port))
        self._server.listen(1)
        self._server.setblocking(False)
        print(f"WebServer: http://{wifi.radio.ipv4_address}:{port}")

    def close(self):
        """Close the listening socket before rebuilding the server."""
        try:
            self._server.close()
        except Exception:
            pass

    @staticmethod
    def _respond(conn, status, body, ctype="text/plain"):
        data = body.encode("utf-8")
        r = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {ctype}; charset=utf-8\r\n"
            f"Content-Length: {len(data)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        payload = r + data
        view = memoryview(payload)
        total = 0
        while total < len(payload):
            sent = conn.send(view[total:])
            if sent <= 0:
                break  # Client disconnected or socket error
            total += sent
        conn.close()

    @staticmethod
    def _serve_file(conn, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
            header = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {ctype}\r\n"
                f"Content-Length: {len(data)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            payload = header + data
            view = memoryview(payload)
            total = 0
            while total < len(payload):
                sent = conn.send(view[total:])
                if sent <= 0:
                    break  # Client disconnected or socket error
                total += sent
        except Exception as e:
            print(f"File serve error {path}: {e}")
            WebServer._respond(conn, "404 Not Found", "Not found")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def tick(self):
        """Poll for new connection. Non-blocking — returns immediately if none."""
        try:
            conn, _ = self._server.accept()
        except OSError:
            return  # No pending connection

        try:
            conn.settimeout(2.0)
            buf = bytearray(512)
            size = conn.recv_into(buf)
            raw = buf[:size].decode("utf-8", "ignore")
            path = raw.split(" ")[1] if " " in raw else "/"

            if path == "/" or path == "/index.html":
                mode = self._mode_mgr.mode
                classes = [
                    "active" if i == mode else "inactive"
                    for i in range(len(MODE_NAMES))
                ]
                html = HTML.format(
                    **{f"cls{i}": c for i, c in enumerate(classes)}
                )
                self._respond(conn, "200 OK", html, "text/html")
            elif path.startswith("/set?mode="):
                new_mode = int(path.split("=")[1]) % len(MODE_NAMES)
                self._mode_mgr.set(new_mode)
                self._respond(conn, "200 OK",
                              f"Switched to: {MODE_NAMES[new_mode]}")
            elif path == "/game":
                self._respond(conn, "200 OK", GAME_HTML, "text/html")
            elif path == "/jump":
                if self._dino_game is not None:
                    self._dino_game.jump()
                self._respond(conn, "200 OK", "ok")
            elif path == "/restart":
                self._respond(conn, "200 OK", "Rebooting...")
                import supervisor
                supervisor.reload()
            elif path == "/apple-touch-icon.png":
                self._serve_file(conn, "/images/apple-touch-icon.png", "image/png")
            else:
                self._respond(conn, "404 Not Found", "Not found")

        except Exception as e:
            print(f"WebServer error: {e}")
            try:
                conn.close()
            except Exception:
                pass
