class ObjCenter:
    """
    Extracts the fire bounding-box centre from a process_fused_detection
    results dictionary.

    Usage
    -----
        obj = ObjCenter(frame_w=640, frame_h=480)

        results = process_fused_detection(frame_v, frame_i, models)
        (obj_x, obj_y), (cx, cy), fire_detected = obj.update(results)

    Returns
    -------
        (obj_x, obj_y)   : pixel centre of the primary fire bounding box.
                           When no fire is detected this equals the frame
                           centre so PID error is zero while scanning.
        (cx, cy)         : frame centre — constant, exposed for convenience.
        fire_detected    : bool — True when meta_decision confirms fire.
    """

    def __init__(self, frame_w: int, frame_h: int):
        """
        Args:
            frame_w: Width  of the visible camera frame in pixels.
            frame_h: Height of the visible camera frame in pixels.
        """
        self.frame_w = frame_w
        self.frame_h = frame_h

        # Frame centre is fixed for a given resolution
        self.cx = frame_w // 2
        self.cy = frame_h // 2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, results: dict):
        """
        Parse a results dict returned by process_fused_detection().

        Expected dict shape (relevant keys only):
            results = {
                'meta_decision': {
                    'fire_detection_boolean': bool,
                    'confidence': float,          # not used here
                    'box': [x1, y1, x2, y2],     # primary fire source
                },
                ...
            }

        Args:
            results: The full results dictionary from process_fused_detection.

        Returns:
            Tuple: ((obj_x, obj_y), (cx, cy), fire_detected)
        """
        meta          = results.get('meta_decision', {})
        fire_detected = meta.get('fire_detection_boolean', False)

        if fire_detected:
            box = meta.get('box', None)
            if box is not None and len(box) == 4:
                x1, y1, x2, y2 = box
                
                # Cast the box center to int for pixel coordinates
                obj_x = int((x1 + x2) / 2.0)
                obj_y = int((y1 + y2) / 2.0)
                
                
                return (obj_x, obj_y), (self.cx, self.cy), True

        # No fire (or malformed box) — return frame centre.
        # The main loop checks fire_detected=False to trigger scanning.
        return (self.cx, self.cy), (self.cx, self.cy), False