import cv2
import torch
import numpy as np
import joblib
import pandas as pd
from ultralytics import YOLO

def initialize_fire_models(vis_path, ir_path, meta_path):
    """
    start loading and prepare the models
    """
    vis_model = YOLO(vis_path, task='detect')
    ir_model = YOLO(ir_path, task='detect')
    meta_learner = joblib.load(meta_path)
    
    return {
        "vis_model": vis_model,
        "ir_model": ir_model,
        "meta_learner": meta_learner
    }

def process_fused_detection(frame_v, 
                            frame_i, 
                            temperature_frame, 
                            models, 
                            temperature_threshold=100.0, 
                            returnAnnotatedImg=False):
    """
    Performs inference and validates IR detections against absolute temperature data.
    """
    # inference
    res_v = models["vis_model"](frame_v, verbose=False, conf=0.497)[0]
    res_i = models["ir_model"](frame_i, verbose=False, conf=0.418)[0]

    def extract_boxes(results):
        if results.boxes is None or len(results.boxes) == 0:
            return {"boxes": [], "confidences": [], "classes": []}
        
        boxes = results.boxes.xyxy.cpu().numpy().tolist()
        confs = results.boxes.conf.cpu().numpy().tolist()
        clss = [results.names[int(c)] for c in results.boxes.cls.cpu().numpy()]
        return {"boxes": boxes, "confidences": confs, "classes": clss}

    raw_v = extract_boxes(res_v)
    raw_i = extract_boxes(res_i)

    def get_max_info(raw_data, label):
        max_conf = 0.0
        max_box = None
        for i, l in enumerate(raw_data["classes"]):
            if l.lower() == label.lower():
                if raw_data["confidences"][i] > max_conf:
                    max_conf = raw_data["confidences"][i]
                    max_box = raw_data["boxes"][i]
        return max_conf, max_box

    # Get Visible features
    vis_f_conf, vis_f_box = get_max_info(raw_v, 'fire')
    vis_s_conf, vis_s_box = get_max_info(raw_v, 'smoke')
    
    # Get IR features
    ir_f_conf, ir_f_box = get_max_info(raw_i, 'fire')

    # here is the thermal validation step
    if ir_f_box is not None:
        # calculate scale factors (Thermal is 256x192, IR Frame is 640x480)
        # scale_x = 256 / 640, scale_y = 192 / 480
        sx, sy = 256/640, 192/480
        
        tx1, ty1 = int(ir_f_box[0] * sx), int(ir_f_box[1] * sy)
        tx2, ty2 = int(ir_f_box[2] * sx), int(ir_f_box[3] * sy)

        # Extract the region from the temperature array
        # Note: we use max() and min() to ensure we stay within array bounds
        temp_roi = temperature_frame[max(0, ty1):min(192, ty2), max(0, tx1):min(256, tx2)]

        # Check if the ROI contains any pixels >= threshold
        if temp_roi.size > 0 and np.max(temp_roi) >= temperature_threshold:
            print(f"{np.max(temp_roi)} >= {temperature_threshold} temperature threshold")
            pass # Keep detection
        else:
            # Suppress detection: Thermal evidence does not support YOLO prediction
            print("Detection Supressed")
            ir_f_conf = 0.0
            ir_f_box = None
            raw_i = {"boxes": [], "confidences": [], "classes": []} # Default to empty for consistency

    # Meta-Learner Prediction
    feature_cols = ["vis_fire_conf", "vis_smoke_conf", "ir_fire_conf"]
    features_df = pd.DataFrame([[vis_f_conf, vis_s_conf, ir_f_conf]], columns=feature_cols)
    
    prob = models["meta_learner"].predict_proba(features_df)[0][1]
    # print("META-LEARNER PROBABILITY: ", prob)
    fire_detected = bool(prob > 0.5)

    results = {
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
            "box": ir_f_box if ir_f_conf > vis_f_conf else vis_f_box
        }
    }

    if returnAnnotatedImg:
        def draw_detections(img, data, color):
            annotated_img = img.copy()
            for i in range(len(data["boxes"])):
                box = data["boxes"][i]
                conf = data["confidences"][i]
                label = data["classes"][i]
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(annotated_img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated_img, f"{label} {conf:.2f}", (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            return annotated_img

        results["annotated_images"] = {
            "visible": draw_detections(frame_v, raw_v, color=(0, 255, 0)),
            "infrared": draw_detections(frame_i, raw_i, color=(0, 0, 255))
        }

    return results