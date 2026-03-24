import cv2

def draw_bounding_boxes(frame, boxes, label="box", color=(0, 0, 255)):
    if boxes == None:
        return
    for i in range(len(boxes)):
        x1 = int(boxes[i][0])
        y1 = int(boxes[i][1])
        x2 = int(boxes[i][2])
        y2 = int(boxes[i][3])
        text = label[i] if label[i] is not None else "Fire"

        #print(x1, y1, x2, y2)

        # Box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Text background
        (font_w, font_h), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
        )

        cv2.rectangle(
            frame,
            (x1, y1 - font_h - baseline),
            (x1 + font_w, y1),
            color,
            -1
        )

        # Text
        cv2.putText(
            frame,
            text,
            (x1, y1 - baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),  # white text
            2
        )
    return frame

