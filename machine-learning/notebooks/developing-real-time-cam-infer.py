'''
Moby Chiu
03/20/2026

This file just tests the real-time inference of visible, infrared, and meta learner model. 
'''

import cv2
import torch
import numpy as np
import pandas as pd
import joblib
from ultralytics import YOLO
from datetime import datetime

# yolo model paths
VIS_MODEL_PATH = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/visible_yolov11n/best_rgb.engine'
IR_MODEL_PATH = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/infrared_yolov11n/best_ir.engine'
META_MODEL_PATH = '/home/firedistinguisher/projects/early-fire-detection-classifier/machine-learning/models/meta-learner/fire_meta_learner.pkl'

VIS_CAM_INDEX = 0
IR_CAM_INDEX = 2

OUTPUT_VIDEO = 'fused_output.mp4'
OUTPUT_CSV = 'fused_telemetry_log.csv'
FRAME_WIDTH, FRAME_HEIGHT = 640, 480

# here we initialize models
print("Initializing Models and Streams...")
vis_model = YOLO(VIS_MODEL_PATH, task='detect')
ir_model = YOLO(IR_MODEL_PATH, task='detect')
meta_learner = joblib.load(META_MODEL_PATH)

cap_vis = cv2.VideoCapture(VIS_CAM_INDEX)
cap_ir = cv2.VideoCapture(IR_CAM_INDEX)

fourcc = cv2.VideoWriter_fourcc(*'mp4v')
video_out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, 25, (FRAME_WIDTH * 2, FRAME_HEIGHT))

# storing data for CSV
telemetry_data = []

def get_yolo_data(results):
    """Extracts lists of coordinates, classes, and confidences for logging."""
    x, y, w, h, cls, conf = [], [], [], [], [], []
    for box in results[0].boxes:
        # xywh format
        coords = box.xywh[0].cpu().numpy()
        x.append(round(float(coords[0]), 2))
        y.append(round(float(coords[1]), 2))
        w.append(round(float(coords[2]), 2))
        h.append(round(float(coords[3]), 2))
        cls.append(results[0].names[int(box.cls[0])])
        conf.append(round(float(box.conf[0]), 3))
    return x, y, w, h, cls, conf

print("Processing... Press 'q' to stop and save.")

frame_count = 0
try:
    while cap_vis.isOpened() and cap_ir.isOpened():
        ret_v, frame_v = cap_vis.read()
        ret_i, frame_i = cap_ir.read()
        if not ret_v or not ret_i: break

        frame_v = cv2.resize(frame_v, (FRAME_WIDTH, FRAME_HEIGHT))
        frame_i = cv2.resize(frame_i, (FRAME_WIDTH, FRAME_HEIGHT))

        # inference
        res_v = vis_model(frame_v, verbose=False)
        res_i = ir_model(frame_i, verbose=False)

        # extract Data for CSV/Logic
        vx, vy, vw, vh, v_cls, v_conf = get_yolo_data(res_v)
        ix, iy, iw, ih, i_cls, i_conf = get_yolo_data(res_i)

        # meta-Learner Features
        # Note: max confidence for target classes as required by your meta-classifier
        vis_f_max = max([c for c, l in zip(v_conf, v_cls) if l.lower() == 'fire'], default=0.0)
        vis_s_max = max([c for c, l in zip(v_conf, v_cls) if l.lower() == 'smoke'], default=0.0)
        ir_f_max = max([c for c, l in zip(i_conf, i_cls) if l.lower() == 'fire'], default=0.0)

        # meta-decisions
        # prob = meta_learner.predict_proba([[vis_f_max, vis_s_max, ir_f_max]])[0][1]
        # prob = models["meta_learner"].predict_proba(features_df)[0][1]
        
        # needed to specify features used from Meta training to keep model happy so it expects this format
        feature_cols = ["vis_fire_conf", "vis_smoke_conf", "ir_fire_conf"]
        features_df = pd.DataFrame([[vis_f_max, vis_s_max, ir_f_max]], columns=feature_cols)
    
        prob = meta_learner.predict_proba(features_df)[0][1]
        
        meta_decision = 1 if prob > 0.5 else 0

        # logging to telemetry list
        telemetry_data.append({
            'frame': frame_count,
            'vis_x': vx, 'vis_y': vy, 'vis_w': vw, 'vis_h': vh, 'vis_class': v_cls, 'vis_conf': v_conf,
            'ir_x': ix, 'ir_y': iy, 'ir_w': iw, 'ir_h': ih, 'ir_class': i_cls, 'ir_conf': i_conf,
            'meta_prob': round(prob, 4),
            'ground_truth_pred': meta_decision
        })

        # UI and saving video
        ann_v = res_v[0].plot()
        ann_i = res_i[0].plot()
        
        status_color = (0, 0, 255) if meta_decision == 1 else (0, 255, 0)
        cv2.putText(ann_v, f"META: {'FIRE' if meta_decision else 'CLEAR'} ({prob:.2%})", 
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)
        
        combined = np.hstack((ann_v, ann_i))
        video_out.write(combined)
        # cv2.imshow('Fusion System', combined)

        frame_count += 1
        # if cv2.waitKey(1) & 0xFF == ord('q'): break
        print ("Frame: ", frame_count, end="")
        if frame_count == 100:
            break

finally:
    # we save to a CSV
    df = pd.DataFrame(telemetry_data)
    df.to_csv(OUTPUT_CSV, index=False)
    
    cap_vis.release()
    cap_ir.release()
    video_out.release()
    cv2.destroyAllWindows()
    print(f"Success. Saved {frame_count} frames to {OUTPUT_VIDEO} and {OUTPUT_CSV}")
