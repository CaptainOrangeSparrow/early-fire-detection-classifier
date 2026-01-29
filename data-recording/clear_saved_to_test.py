import os
import shutil

src_parent = r"saved_recordings"
dst_parent = r"test_recordings"

for name in os.listdir(src_parent):
    src_path = os.path.join(src_parent, name)
    dst_path = os.path.join(dst_parent, name)

    if os.path.isdir(src_path):
        print(f"Moving: {src_path} -> {dst_path}")
        shutil.move(src_path, dst_path)

print("Done.")

