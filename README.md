### Installation
- flash pi os-lite (with gadget mode enabled) onto the raspberry
    -> instructions on configuring gadget mode: https://www.raspberrypi.com/news/usb-gadget-mode-in-raspberry-pi-os-ssh-over-usb/
- on pi: install dependencies using`sudo apt-get install python3-opencv` `sudo apt-get install python3-pygame` `sudo apt-get install python3-rpi.gpio` `python3 -m pip3 install adafruit-circuitpython-servokit` (this one can only be installed directly through pip, ignore the warning it gives you about the externally managed environment and force install)

- on main machine: install requirements.txt
- on main machine: install comfyUI desktop and download the 3d_hunyuan3d_multiview_to_model_turbo workflow 
- upload pi_script to raspberry using scp <your-path>/trashpi/* trash@10.12.194.1:~
- adjust endpoints for image sync in trash3Dgen

### init
- connect pi to main machine using usb c, connect usb camera to pi
- create a ssh connection to the pi using ssh trash@10.12.194.1
- on pi: start pi_script 
- on main machine: open comfyUI desktop, start trashsite script, trashsync script and trash3Dgen script

### Workflow
- pi_script takes 4 images (front, left, back, right) of an object and stores the images in folder trash_imgs
- images are synced to the main machine through network using trashsync, should end up in folder image_in
- trash3Dgen listens to folder image_in and triggers the comfyUI imageTo3D workflow when a new object emerges
- comfyUI stores them in object_out
- trashsite3D listens for new images in object_out and adds them to the local website

### Troubleshooting

list all network devices with `arp -a`

pi: list usb devices using `lsusb`

**In order for gadget mode to work, PC can’t be connected to the network!!!**

### Cleanup

clear image folder on the pi using `rm -rf /home/trash/trash_imgs`

clear comfyUI output folder
