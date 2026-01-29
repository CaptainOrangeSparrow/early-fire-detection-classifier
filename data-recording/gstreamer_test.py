import cv2

device = "/dev/video0"  # <-- change to the MJPG node you found
gst = (
    f"v4l2src device={device} io-mode=2 ! "
    "image/jpeg,width=1280,height=720,framerate=30/1 ! "
    "jpegdec ! videoconvert ! "
    "appsink drop=true max-buffers=1 sync=false"
)

cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)
print("opened:", cap.isOpened())

ret, frame = cap.read()
print("first read:", ret, None if not ret else frame.shape)

cap.release()

