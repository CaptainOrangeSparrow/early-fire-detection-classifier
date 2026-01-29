import argparse
import cv2
import glob
import os

def count_frames_in_video(video_path):
    """
    Counts the total number of frames in a single video file using OpenCV.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error opening video file: {video_path}")
        return None
    
    # Use the built-in property for frame count (fast method)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    
    # Note: The built-in property is usually fast but may be inaccurate for some codecs/files.
    # A slower, more accurate method involves iterating through every frame.
    if frame_count <= 0:
        print(f"Metadata frame count is 0 for {video_path}, falling back to manual count.")
        frame_count = count_frames_manually(video_path)

    return frame_count

def count_frames_manually(video_path):
    """
    Manually iterates through all frames to get an accurate count (slow method).
    """
    cap = cv2.VideoCapture(video_path)
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        count += 1
    cap.release()
    return count

def process_directory(parent_dir):
    """
    Finds all MP4 files in the directory and prints their frame counts.
    """
    # Use glob to find all .mp4 files (case-insensitive and non-recursive)
    search_path = os.path.join(parent_dir, '*.mp4')
    video_files = glob.glob(search_path)
    
    if not video_files:
        print(f"No MP4 files found in the directory: {parent_dir}")
        return

    print(f"Found {len(video_files)} MP4 files. Processing...")

    for video_file in video_files:
        frame_count = count_frames_in_video(video_file)
        if frame_count is not None:
            print(f"* {os.path.basename(video_file)}: {frame_count} frames")

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Count the number of frames of each MP4 file in a specified directory.")
    parser.add_argument("parent_dir", type=str, help="The path to the parent directory containing MP4 files.")
    
    args = parser.parse_args()
    
    # Validate the input directory
    if not os.path.isdir(args.parent_dir):
        print(f"Error: Directory not found at {args.parent_dir}")
    else:
        process_directory(args.parent_dir)


