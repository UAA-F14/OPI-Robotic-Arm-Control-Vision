"""Pagina web propia (sin Flask, solo http.server) para ver el video en
vivo con el esqueleto dibujado encima -- nada de X11 ni VNC, mucho mas
ligero para la red."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

HTTP_PORT = 5000

_frame_lock = threading.Lock()
_latest_jpeg = None

_PAGE_HTML = (
    b"<html><body style='margin:0;background:#000'>"
    b"<img src='/video_feed' style='width:100%;height:auto;display:block'>"
    b"</body></html>"
)


def publish_preview_frame(frame):
    global _latest_jpeg
    # calidad moderada a proposito -- el preview es solo para ver, no
    # afecta la deteccion, y asi pesa menos para mandarlo por la red.
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if ok:
        with _frame_lock:
            _latest_jpeg = buf.tobytes()


class _StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # sin esto imprime una linea por cada frame

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(_PAGE_HTML)))
            self.end_headers()
            self.wfile.write(_PAGE_HTML)
            return

        if self.path == "/video_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _frame_lock:
                        jpeg = _latest_jpeg
                    if jpeg is not None:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self.send_response(404)
        self.end_headers()


def start_preview_server():
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), _StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


class FrameGrabber:
    """Lee la camara en su propio hilo, sin parar, y solo se queda con el
    frame mas reciente. Si la deteccion tarda mas que la camara en mandar
    frames, se saltan los viejos en vez de acumularse en fila -- eso es lo
    que causaba que el video se viera "del pasado" aunque fuera fluido."""

    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        self.lock = threading.Lock()
        self.frame = None
        self.running = self.cap.isOpened()
        if self.running:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                self.running = False
                break
            with self.lock:
                self.frame = frame

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def release(self):
        self.running = False
        self.cap.release()
