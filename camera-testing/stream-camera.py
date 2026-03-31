# Video Stream
import cv2
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--device", type=int, default=4, help="device id of camera stream to run")

args = parser.parse_args()
device_id = args.device

cap = cv2.VideoCapture(device_id, cv2.CAP_V4L2)

# Set stuff for low res for rgb. Remove for ir
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 10)

if not cap.isOpened():
    print("Error: could not open camera.")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read frame.")
        break
    cv2.imshow('Camera Stream', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
    
