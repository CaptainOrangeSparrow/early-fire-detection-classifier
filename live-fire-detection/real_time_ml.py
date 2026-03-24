import cv2
import torch
import numpy as np
import joblib
from ultralytics import YOLO

def initialize_fire_models(vis_path, ir_path, meta_path):
    """
    start loading and  prepare the models
    """
    vis_model = YOLO(vis_path, task='detect')
    ir_model = YOLO(ir_path, task='detect')
    meta_learner = joblib.load(meta_path)
    
    return {
        "vis_model": vis_model,
        "ir_model": ir_model,
        "meta_learner": meta_learner
    }

def process_fused_detection(frame_v, frame_i, models):
    """
    This will perform our inference and returns a structured dictionary of results.
    """
    # inference
    res_v = models["vis_model"](frame_v, verbose=False)[0]
    res_i = models["ir_model"](frame_i, verbose=False)[0]

    def extract_boxes(results):
        # extractting raw YOLO boxes, classes, and confidences
        boxes = results.boxes.xyxy.cpu().numpy().tolist()  # note: [x1, y1, x2, y2]
        confs = results.boxes.conf.cpu().numpy().tolist()
        clss = [results.names[int(c)] for c in results.boxes.cls.cpu().numpy()]
        return {"boxes": boxes, "confidences": confs, "classes": clss}

    raw_v = extract_boxes(res_v)
    raw_i = extract_boxes(res_i)

    # Extract the MAX confidences for our meta-learner
    # also helper to find max conf and its specific box for a specific label
    def get_max_info(raw_data, label):
        max_conf = 0.0
        max_box = None
        for i, l in enumerate(raw_data["classes"]):
            if l.lower() == label.lower():
                if raw_data["confidences"][i] > max_conf:
                    max_conf = raw_data["confidences"][i]
                    max_box = raw_data["boxes"][i]
        return max_conf, max_box

    vis_f_conf, vis_f_box = get_max_info(raw_v, 'fire')
    vis_s_conf, vis_s_box = get_max_info(raw_v, 'smoke')
    ir_f_conf, ir_f_box = get_max_info(raw_i, 'fire')

    # Meta-Learner Decision
    # Note Features: [Visible Fire Max, Visible Smoke Max, IR Fire Max]
    prob = models["meta_learner"].predict_proba([[vis_f_conf, vis_s_conf, ir_f_conf]])[0][1]
    fire_detected = bool(prob > 0.5)

    # returning dictionary containing info
    return {
        "raw_detections": {
            "visible": raw_v,
            "infrared": raw_i
        },
        "extracted_features": {
            "vis_fire_max": {"conf": vis_f_conf, "box": vis_f_box},
            "vis_smoke_max": {"conf": vis_s_conf, "box": vis_s_box},
            "ir_fire_max": {"conf": ir_f_conf, "box": ir_f_box}
        },
        "meta_decision": {
            "fire_detection_boolean": fire_detected,
            "confidence": round(float(prob), 4),
            # we will treat the best box as the meta-box (usually the IR or Vis fire box)
            "box": ir_f_box if ir_f_conf > vis_f_conf else vis_f_box
        }
    }

def draw_bounding_boxes(frame, boxes):
    if boxes == None:
        return
    for box in boxes:
        x1 = int(box[0])
        y1 = int(box[1])
        x2 = int(box[2])
        y2 = int(box[3])
        label = "Fire"

        print(x1, y1, x2, y2)

        # Box
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

        # Text background
        (font_w, font_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
        )

        cv2.rectangle(
            frame,
            (x1, y1 - font_h - baseline),
            (x1 + font_w, y1),
            (0, 0, 255),
            -1
        )

        # Text
        cv2.putText(
            frame,
            label,
            (x1, y1 - baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),  # white text
            2
        )
        return frame
    

