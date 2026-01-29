
===================
Readme.txt

record.py is the main recording script. 
Activate the conda env named recording.
Do python record.py -h for more details about its params

Note: If --web-preview is used, to view the web app on your local browser at localhost:5000, 
	you need to have ssh-ed in with the following or open another terminal and do another ssh:

	ssh -J eid@mario.ece.utexas.edu -p 2000 firedistinguisher@localhost -L 5000:localhost:5000 -Y

	If you get a bunch of channel open failed, that is the browser trying to connect when the script
	is not running. So when not using the script, close the browser tab if you want to remove that message.


Recommended use: python record.py [name] --no-gui --web-preview (--view-only if not recording)

You can change whether the thermal camera frames use Min-Max Normalization or Fixed Ranged Normalization by changing
a setting on Line 147 in peripherals/cameras.py

Directories:
- saved_recordings[dir] is the default location that new recordings are saved.
- peripherals[dir] and utilities[dir] are extra helper python modules to help record.py function

Recordings are saved in the following format:
- New directory created and named appropriately
- .mp4 for rgb camera
- .mp4 for ir camera
- .csv for all channels of the ADC
- .json to hold metadatda
- .npz files for raw thermal data (stored in raw_ir [directory])

- The rows of the csv file should match up with the frames of the mp4 files
- The new directory created will have the name, desired fps, date, index, unix time, and time.
  The index increments when there is a recording with the same date in the same destination directory
- The arrays in the npz files store the raw 192x256 data in row major order (top left corner is 0,0, +y axis down, +x axis right). Frame number is also stored along with the arrays

Other scripts:
- clear_saved_to_test.py is a script that moves all the recordings in the saved_recordings directory into the test_recordings directory.
- gstreamer-test.py is a script to test gstreamer pipelines when opening camera devices with python scripts.
- verify-frame-count.py counts the number of frames of all .mp4 files in a given directory.

-Michael

===================

