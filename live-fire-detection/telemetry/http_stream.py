from flask import Flask, Response
import cv2
import threading
import time

class HTTPStreamServer:

    def __init__(self, display, host="0.0.0.0", port=5000):
        self.display = display
        self.host = host
        self.port = port
        self.app = Flask(__name__)

        @self.app.route("/")
        def index():
            return """
            <html>
            <head><title>Telemetry Preview</title></head>
            <body>
            <h2>Jetson Telemetry Display</h2>
            <img src="/video">
            </body>
            </html>
            """

        @self.app.route("/video")
        def video():
            return Response(self.frame_generator(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

    def frame_generator(self):
        while True:

            frame = self.display.get_latest_frame()

            if frame is None:
                time.sleep(0.02)
                continue

            ret, jpeg = cv2.imencode(".jpg", frame)

            if not ret:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                jpeg.tobytes() +
                b"\r\n"
            )

    def start(self):
        thread = threading.Thread(
            target=lambda: self.app.run(
                host=self.host,
                port=self.port,
                threaded=True,
                use_reloader=False
            ),
            daemon=True
        )

        thread.start()
