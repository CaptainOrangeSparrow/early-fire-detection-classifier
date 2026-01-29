import cv2
from flask import Flask, Response
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--device", type=int, default=4, help="device id of camera stream to run")
parser.add_argument("--flip", action="store_true", help="flip camera view by 180 degrees")
args = parser.parse_args()

cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    raise RuntimeError("Could not open camera.")

app = Flask(__name__)

def gen_frames():
    while True:
        success, frame = cap.read()
        if not success:
            break

        if args.flip:
            frame = cv2.rotate(frame, cv2.ROTATE_180)

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100, threaded=True)

