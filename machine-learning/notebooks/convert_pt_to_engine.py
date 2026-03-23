'''
THIS IS TO BE RUN ON THE JETSON ORIN NANO WHICH CONVERTS .pt to .engine 
CONVERSION WILL NOT WORK IF RUN ON SEPARATE DEVICE AND RUN ON NANO ORIN
'''

from ultralytics import YOLO

# lload your PyTorch models
model_vis = YOLO("visible_model.pt")
model_ir = YOLO("infrared_model.pt")

# export with specific 640x480 resolution
# imgsz is (height, width) or [height, width]
print("Starting export... this may take several minutes.")
model_vis.export(format='engine', imgsz=[480, 640], device=0, half=True, optimize=True) #optimize may not be valid parameter here (https://docs.ultralytics.com/modes/export/#export-formats)
model_ir.export(format='engine', imgsz=[480, 640], device=0, half=True, optimize=True)

print("Export Complete. You now have 'visible_model.engine' and 'infrared_model.engine'.")