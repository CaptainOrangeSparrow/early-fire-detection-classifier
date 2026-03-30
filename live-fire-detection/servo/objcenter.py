class ObjCenter:
    """
    Object centering logic for pan-tilt tracking.
    """

    def __init__(self, frame_w: int, frame_h: int):
        """
        frame_w: Width  of the camera frame in pixels.
        frame_h: Height of the camera frame in pixels.
        """
        self.frame_w = frame_w
        self.frame_h = frame_h

        # Frame center is fixed for a given resolution
        self.cx = frame_w // 2
        self.cy = frame_h // 2

    def update(self, results: dict):
        """
        Parse a results dict returned by process_fused_detection().

        results: The full results dictionary from process_fused_detection.

        Returns:
            Tuple: ((obj_x, obj_y), (cx, cy), fire_detected)
        """
        meta          = results.get('meta_decision', {})
        fire_detected = meta.get('fire_detection_boolean', False)

        # Extract centroid of detected fire box if fire is detected
        if fire_detected:
            box = meta.get('box', None)
            if box is not None and len(box) == 4: # ensure box is well-formed
                x1, y1, x2, y2 = box
                
                # Cast the box center to int for pixel coordinates
                obj_x = int((x1 + x2) / 2.0)
                obj_y = int((y1 + y2) / 2.0)
                
                
                return (obj_x, obj_y), (self.cx, self.cy), True

        # The main loop checks fire_detected=False to trigger scanning.
        return (self.cx, self.cy), (self.cx, self.cy), False