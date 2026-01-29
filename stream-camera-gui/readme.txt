===================

constants.py
- file to store global constants for easy access and so it is also accessible from all other modules/files

gui.py
- integrated IR camera stream with Moby's original gui

gui-new.py
- integrated both IR and RGB camera streams with a new gui layout

peripherals [dir]
- folder containing python modules to inteface sensors with the gui

	cameras.py
	- contains classes for RBG and IR cameras to be intialized and used elsewhere with functions to read frames.
	  supports multiple things accessing it at once.

gui-assets [dir]
- folder containing resources to support the gui such as downloaded fonts, images, etc.

saved_recordings [dir]
- folder containing saved recordings to be played back in the gui.
  future recordings could be saved here from the gui.


===================


