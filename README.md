# Early-fire-detection-classifier

## Description

This repository aims to detect fires at an early stage and classify the type of fire using sensor-fusion techniques and machine learning. The project is from the University of Texas at Austin's engineering senior design group Spring 2026.

## Things that are Good to Know

### GIT

Git on the jetson will be setup using the SSH key route. Any git actions will not prompt a log in due to the stored SSH deploy key. Pushes will be recorded as have been made by the deploy key. Whoever is registered on the jetson's git config global user.email will show up as the user responsible of a commit at the time of commit.

To change the git config global user:

```git config --global user.email [git email here]```

When you want to do a commit, change the git config global user email to your git email or sign your first name at the end of your commit message (For example add file -firstname).

-----

### SSH

To log onto the jetson from the ECE-LRC servers:

```ssh firedistinguisher@localhost -p 2000```

To log onto the jetson from the ECE-LRC servers with video forwarding:

```ssh firedistinguisher@localhost -p 2000 -Y```

To log onto the jetson from your laptop through the ECE-LRC servers to support web-streaming from local host on the jeston to your local browser:

```ssh ssh -J eid@mario.ece.utexas.edu -p 2000 firedistinguisher@localhost -L [port]:localhost:[port]```

- Replace [port] with the port number the web stream is hosted on or streaming to

-----

### CONDA Virtual Environment Manager

Available CONDA environments:

- base
- app
- appgui
- cameragui
- recording
- telemetry

Please do not modify the base environment.

-----

## Repository Structure

**I2C-testing**

This folder contains code to test accessing read-write functionality on the I2C bus using python smbus2 module for various connected devices including the ADC and HDC. Use i2cdetect -r to scan I2C busses for connected devices.

- ```basic-I2C.py``` sends read and write commands on the i2c bus
- ```ads1115-i2c.py``` is a class that reads values from the ads1115 modules
- ```hdc3022.py``` is a class that reads values from the hdc3022 temp and humidity sensor

Requires ```recording``` conda env.

-----

**audio-testing**

This folder contains code for testing the MAX98357A Audio Amp for producing audio from the jetson using the I2S protocol. 

- ```play-tone.py``` plays a sine wave for a specified duration and frequency
- ```play-wav.py``` plays a wav file

Requires ```recording``` conda env.

-----

**camera-gui**

This folder contains original python gui that was developed to play prerecorded mp4 files. A pyside 6 gui application is used to display the videos and interactive buttons.

- ```camera_gui.ipynb``` is the original python notebook that was used to develop the initial gui
- ```camera_gui.py``` is the python version of the ipynb notebook  
- ```test.txt``` is a test file

Requires ```cameragui``` conda env.

-----

**camera-testing**

This folder contains tools to view the raw camera streams for RGB and IR cameras. In particular, it contains code for the tc001. The raw camera streams open native openCV windows or host a web stream. NOTE: The tc001 code came from another repo leswright pythermalcam and contains some erroneous temperature decoding code. (That is fixed in the data recording camera module)

- ```readme```: This folder comes with its own readme. See readme for more details
- ```web-stream-camera.py``` is the web stream version of stream-camera.py. Note: to use the web-stream, the ssh port forwarding needs to be used. (See web stream ssh command above).

Requires ```cameragui``` conda env.

-----

**data-recording**

This is the main data recording software folder. Multi-modal data is recorded and streamed using either a pyside6 gui application, console only mode, or web stream application (recommended). Data is recorded at a default 25 FPS.

Recordings are saved to saved_recordings [dir] and test_recordings [dir] hold recordings that were taken just for testing and are kept for historical purposes.

- ```readme.txt```: This folder comes with its own readme. See readme for more details
- ```record.py``` is the main data recording script```
- ```utilities``` [dir] holds utility modules such as writers, web stream host server, html, javascript, etc. and other helpful utility code
- ```peripherals``` [dir] holds modules containing classes to read info and interact with connected external devices such as cameras and adcs.
- ```saved_recordings``` [dir] holds saved recordings
- ```test_recordings``` [dir] holds test recordings
- ```clear_Saved_to_test.py``` is a helper script to move all recordings in saved_recordings to test_recordings
- ```gstreamer_test.py``` is a helper script to test using gstreamer to run nvidia hardware optimized camera frames
- ```verify-frame-count.py``` is a helper script to count the number of frames in every mp4 file in a specified directory (does not search child directories)

Requires ```recording``` conda env.

-----

**downloads**

The purpose of this folder is to store files in transit (Files that needed to be copied over into or exported out of the jeston).

-----

**stream-camera-gui**

This folder contains files to stream both RGB and IR camera feeds simultaneously with a more custom gui in a pyside6 application

- ```readme.txt```: This folder comes with its own readme. See readme for more details. This readme has details for the rest of the components in the folder and therefore the other contents in the folder won't be listed again here.

Requires ```appgui``` conda env.

-----

**telemetry-display**

This folder contains files to stream data to a ST7735 LCD display.

Requires ```telemetry``` conda env.

-----

**test-files**

This folder contains miscellaneous test files.

----

## Additional Notes


Thanks, add anything other considerations here if need be.


Michael

