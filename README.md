### Installation
- install requirements.txt
- install comfyUI desktop and download the 3d_hunyuan3d_multiview_to_model_turbo workflow 
- upload pi_script to raspberry, adjust endpoints for image sync

### init
- setup pi and main machine to access the same network (important as they communicate via localhost)
- start pi_script on pi
- open comfyUI desktop, start trashsite script and trash3Dgen script

### Workflow
- pi_script takes 4 images (front, left, back, right) of an object and stores the images in folder trash_imgs
- images are synced to the main machine through network, should end up in folder image_in
- trash3Dgen listens to folder image_in and triggers the comfyUI imageTo3D workflow when a new object emerges
- comfyUI stores them in object_out
- trashsite3D listens for new images in object_out and adds them to the local website
