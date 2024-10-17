    #!/usr/bin/env python3
import json
import queue
import time
from multiprocessing import Process, Manager
from typing import Optional
import os
import requests
from communication.android import AndroidLink, AndroidMessage
from communication.stm32 import STMLink
from logger import prepare_logger
from settings import API_IP, API_PORT, IMG_IP, IMG_PORT
from PIL import Image,ImageDraw, ImageFont
from picamera import PiCamera
import glob
import shutil
from datetime import datetime

class PiAction:
    def __init__(self, cat, value):
        self._cat = cat
        self._value = value

    @property
    def cat(self):
        return self._cat

    @property
    def value(self):
        return self._value


class RaspberryPi:
    def __init__(self):
        # Initialize logger and communication objects with Android and STM
        self.logger = prepare_logger()
        self.android_link = AndroidLink()
        self.stm_link = STMLink()

        # For sharing information between child processes
        self.manager = Manager()

        # Set robot mode to be 1 (Path mode)
        self.robot_mode = self.manager.Value('i', 1)

        # Events
        self.android_dropped = self.manager.Event()  # Set when the android link drops
        # commands will be retrieved from commands queue when this event is set
        self.unpause = self.manager.Event()

        # Movement Lock
        self.movement_lock = self.manager.Lock()

        # Queues
        self.android_queue = self.manager.Queue() # Messages to send to Android
        self.rpi_action_queue = self.manager.Queue() # Messages that need to be processed by RPi
        self.command_queue = self.manager.Queue() # Messages that need to be processed by STM32, as well as snap commands

        # Define empty processes
        self.proc_recv_android = None
        self.proc_recv_stm32 = None
        self.proc_android_sender = None
        self.proc_command_follower = None
        self.proc_rpi_action = None

        self.ack_count = 0

    def start(self):
        """Starts the RPi orchestrator"""
        try:
            # Establish Bluetooth connection with Android
            self.android_link.connect()
            self.android_queue.put(AndroidMessage('info', 'You are connected to the RPi!'))

            # Establish connection with STM32
            self.stm_link.connect()

            # Check Image Recognition and Algorithm API status
            self.check_api() #commented out
            
            #self.small_direction = self.snap_and_rec("Small")
            #self.logger.info(f"PREINFER small direction is: {self.small_direction}")

            # Define child processes
            self.proc_recv_android = Process(target=self.recv_android)
            self.proc_recv_stm32 = Process(target=self.recv_stm)
            self.proc_android_sender = Process(target=self.android_sender)
            self.proc_command_follower = Process(target=self.command_follower)
            self.proc_rpi_action = Process(target=self.rpi_action)

            # Start child processes
            self.proc_recv_android.start()
            self.proc_recv_stm32.start()
            self.proc_android_sender.start()
            self.proc_command_follower.start()
            self.proc_rpi_action.start()

            self.logger.info("Child Processes started")

            ### Start up complete ###

            # Send success message to Android
            self.android_queue.put(AndroidMessage('info', 'Robot is ready!'))
            self.android_queue.put(AndroidMessage('mode', 'path' if self.robot_mode.value == 1 else 'manual'))
            
            
            
            # Handover control to the Reconnect Handler to watch over Android connection
            self.reconnect_android()

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stops all processes on the RPi and disconnects gracefully with Android and STM32"""
        self.android_link.disconnect()
        self.stm_link.disconnect()
        self.logger.info("Program exited!")

    def reconnect_android(self):
        """Handles the reconnection to Android in the event of a lost connection."""
        self.logger.info("Reconnection handler is watching...")

        while True:
            # Wait for android connection to drop
            self.android_dropped.wait()

            self.logger.error("Android link is down!")

            # Kill child processes
            self.logger.debug("Killing android child processes")
            self.proc_android_sender.kill()
            self.proc_recv_android.kill()

            # Wait for the child processes to finish
            self.proc_android_sender.join()
            self.proc_recv_android.join()
            assert self.proc_android_sender.is_alive() is False
            assert self.proc_recv_android.is_alive() is False
            self.logger.debug("Android child processes killed")

            # Clean up old sockets
            self.android_link.disconnect()

            # Reconnect
            self.android_link.connect()

            # Recreate Android processes
            self.proc_recv_android = Process(target=self.recv_android)
            self.proc_android_sender = Process(target=self.android_sender)

            # Start previously killed processes
            self.proc_recv_android.start()
            self.proc_android_sender.start()

            self.logger.info("Android child processes restarted")
            self.android_queue.put(AndroidMessage("info", "You are reconnected!"))
            self.android_queue.put(AndroidMessage('mode', 'path' if self.robot_mode.value == 1 else 'manual'))

            self.android_dropped.clear()
            
        
    def recv_android(self) -> None:
        """
        [Child Process] Processes the messages received from Android
        """
       
        while True:
            msg_str: Optional[str] = None
            try:
                msg_str = self.android_link.recv()
            except OSError:
                self.android_dropped.set()
                self.logger.debug("Event set: Android connection dropped")

            # If an error occurred in recv()
            if msg_str is None:
                continue

            message: dict = json.loads(msg_str)

            ## Command: Start Moving ##
            if message['cat'] == "control":
                if message['value'] == "start":
        
                    if not self.check_api():
                        self.logger.error("API is down! Start command aborted.")

                    self.clear_queues()
                    self.command_queue.put(["FP_1", 3000, 100, 50]) # ack_count = 1

                    
                    # Small object direction detection
                    """self.small_direction = self.snap_and_rec("Small")
                    self.logger.info(f"HERE small direction is: {self.small_direction}")
                    if self.small_direction == "Left": 
                        self.command_queue.put(["FORWARD_TURN", 1500, 40, 25])
                        self.command_queue.put(["FORWARD", 1000, 25, 0]) 
                        self.command_queue.put(["FORWARD_TURN", 1500, -120, 60]) 
                        self.command_queue.put(["FORWARD_TURN", 1000, -20, 10]) 
                        self.command_queue.put(["FORWARD_TURN", 1000, 60, 30]) 
                        self.command_queue.put(["FP_1", 2500, 100, 30])
                    elif self.small_direction == "Right":
                        self.command_queue.put(["FORWARD_TURN", 1500, -40, 30]) 
                        self.command_queue.put(["FORWARD", 1000, 30, 0]) 
                        self.command_queue.put(["FORWARD_TURN", 1500, 100, 40]) 
                        self.command_queue.put(["FORWARD_TURN", 1000, 20, 15]) 
                        self.command_queue.put(["FORWARD_TURN", 1000, -100, 35]) 
                        self.command_queue.put(["FP_1", 2500, 100, 30])
                    elif self.small_direction == None or self.small_direction == 'None':
                        self.logger.info("Acquiring near_flag log")
                        self.near_flag.acquire()       """      
                        
                        #self.command_queue.put("OB01") # ack_count = 3
                        

                    self.logger.info("Start command received, starting robot on Week 9 task!")
                    self.android_queue.put(AndroidMessage('status', 'running'))

                    # Commencing path following | Main trigger to start movement #
                    self.unpause.set()
                    
    def recv_stm(self) -> None:
        """
        [Child Process] Receive acknowledgement messages from STM32, and release the movement lock
        """
        while True:

            message: str = self.stm_link.recv()
            # Acknowledgement from STM32
            if message.startswith("0"):

                self.ack_count += 1

                # Release movement lock
                try:
                    self.movement_lock.release()
                except Exception:
                    self.logger.warning("Tried to release a released lock!")

                self.logger.debug(f"ACK from STM32 received, ACK count now:{self.ack_count}")
                
                
                self.logger.info(f"self.ack_count: {self.ack_count}")
                if self.ack_count == 1:
                    try:
                    
                        #self.near_flag.release()
                        self.logger.debug("First ACK received, robot reached first obstacle!")
                        self.small_direction = self.snap_and_rec("Small_Near")
                        if  self.small_direction == 'Left': 
                            self.command_queue.put(["FORWARD_TURN", 2000, 45, 30])
                            self.command_queue.put(["FORWARD", 1000, 15, 0]) 
                            self.command_queue.put(["FORWARD_TURN", 2000, -45, 30]) 
                            self.command_queue.put(["FORWARD", 1000, 20, 0]) 
                            self.command_queue.put(["FORWARD_TURN", 2000, -45, 30])
                            self.command_queue.put(["FORWARD", 1000, 15, 0]) 
                            self.command_queue.put(["FORWARD_TURN", 2000, 45, 30]) 
                            self.command_queue.put(["FP_1", 3000, 200, 30])
                        else:
                            self.command_queue.put(["FORWARD_TURN", 2000, -45, 30])
                            self.command_queue.put(["FORWARD", 1000, 15, 0]) 
                            self.command_queue.put(["FORWARD_TURN", 2000, 45, 30]) 
                            self.command_queue.put(["FORWARD", 1000, 20, 0]) 
                            self.command_queue.put(["FORWARD_TURN", 2000, 45, 30])
                            self.command_queue.put(["FORWARD", 1000, 15, 0])  
                            self.command_queue.put(["FORWARD_TURN", 2000, -45, 30]) 
                            self.command_queue.put(["FP_1", 3000, 200, 30])
                        
                    except:
                        self.logger.info("No need to release near_flag")
                '''
                if self.ack_count == 5:
                    self.large_direction = self.snap_and_rec("Large")
                    if  self.small_direction == 'Left': 
                        self.command_queue.put(["FORWARD_TURN", 2000, -45, 30]) 
                        self.command_queue.put(["FORWARD_TURN", 2000, 45, 30]) 
                        self.command_queue.put(["FP_1", 3000, 200, 30])
                    elif self.small_direction == 'Right':
                        self.command_queue.put(["FORWARD_TURN", 2000, 45, 30]) 
                        self.command_queue.put(["FORWARD_TURN", 2000, -45, 30]) 
                        self.command_queue.put(["FP_1", 3000, 200, 30])
                    else:
                        self.command_queue.put(["FORWARD_TURN", 2000, 45, 30]) 
                        self.command_queue.put(["FORWARD_TURN", 2000, -45, 30]) 
                        self.command_queue.put(["FP_1", 3000, 200, 30])
                        self.logger.debug("Failed first one, going left by default!")
                '''
                if self.ack_count == 9:
                    RIGHT = 0
                    LEFT = 1
                    self.large_direction = self.snap_and_rec("Large")
                    try:
                        #time.sleep(2)
                        self.logger.debug("First ACK received, robot finished first obstacle!")
                        if self.large_direction == "Left":
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_UPO", 2000, 40, RIGHT])
                            #self.command_queue.put(["FORWARD", 2000, 10, 0])
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_UDO", 2000, 40, RIGHT])
                            self.command_queue.put(["FORWARD_UPO", 2000, 40, RIGHT])
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["FP_2", 3000, 0, 70])
                            self.command_queue.put(["FORWARD", 2000, 20, 0])
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["BACKWARD", 2000, 30, 0])
                            self.command_queue.put(["FORWARD_UDO", 2000, 30, RIGHT])
                            self.command_queue.put(["BACKWARD", 2000, 10, 0])
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["FP_1", 2000, 100, 20])
                        else:
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_UPO", 2000, 40, LEFT])
                            #self.command_queue.put(["FORWARD", 2000, 10, 0])
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["FORWARD_UDO", 2000, 40, LEFT])
                            self.command_queue.put(["FORWARD_UPO", 2000, 40, LEFT])
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["FP_2", 3000, 0, 70])
                            self.command_queue.put(["FORWARD", 2000, 20, 0])
                            self.command_queue.put(["FORWARD_LEFT2", 3000, 70, 0])
                            self.command_queue.put(["BACKWARD", 2000, 30, 0])
                            self.command_queue.put(["FORWARD_UDO", 2000, 40, LEFT])
                            self.command_queue.put(["BACKWARD", 2000, 10, 0])
                            self.command_queue.put(["FORWARD_RIGHT2", 3000, 70, 0])
                            self.command_queue.put(["FP_1", 2000, 100, 15])
                        '''else:
                            self.command_queue.put(["FORWARD_RIGHT", 1000, 70, 0])
                            self.command_queue.put(["FORWARD_UPO", 1500, 100, 1])
                            self.command_queue.put(["BACKWARD", 2000, 20, 0])
                            self.command_queue.put(["FORWARD_LEFT", 1000, 60, 0])
                            self.command_queue.put(["FORWARD_LEFT", 1000, 60, 0])
                            self.command_queue.put(["FORWARD_UPO", 1500, 100, 1])
                            self.command_queue.put(["FORWARD_LEFT", 1000, 60, 0])
                            self.command_queue.put(["FP_2", 2000, 0, 70])
                            self.command_queue.put(["FORWARD_LEFT", 1000, 60, 0])
                            self.command_queue.put(["BACKWARD", 2000, 40, 0])
                            self.command_queue.put(["FORWARD_RIGHT", 1000, 70, 0])
                            self.command_queue.put(["FP_1", 1000, 100, 20])
                            self.logger.debug("Failed second one, going right by default!")'''
                    except:
                        self.logger.info("No need to release near_flag")

                if self.ack_count == 12:
                    self.logger.debug("Second ACK received from STM32!")
                    self.android_queue.put(AndroidMessage("status", "finished"))
                    self.command_queue.put("FIN")

                # except Exception:
                #     self.logger.warning("Tried to release a released lock!")
            else:
                self.logger.warning(
                    f"Ignored unknown message from STM: {message}")

    def android_sender(self) -> None:
        while True:
            try:
                message: AndroidMessage = self.android_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self.android_link.send(message)
            except OSError:
                self.android_dropped.set()
                self.logger.debug("Event set: Android dropped")

    def command_follower(self) -> None:
        while True:
            command: list = self.command_queue.get()
            self.unpause.wait()
            self.movement_lock.acquire()
            stm32_prefixes = ("FS", "BS", "FW", "BW", "FL", "FR", "BL",
                              "BR", "TL", "TR", "A", "C", "DT", "STOP", "ZZ", "RS")
            if command == "FIN":
                self.unpause.clear()
                self.movement_lock.release()
                self.logger.info("Commands queue finished.")
                self.android_queue.put(AndroidMessage("info", "Commands queue finished."))
                self.android_queue.put(AndroidMessage("status", "finished"))
                self.rpi_action_queue.put(PiAction(cat="stitch", value=""))
            else:
                self.stm_link.send_week9(command)
                self.logger.debug(f"Sending to STM32: {command}")
                time.sleep(1)

    def rpi_action(self):
        while True:
            action: PiAction = self.rpi_action_queue.get()
            self.logger.debug(f"PiAction retrieved from queue: {action.cat} {action.value}")
            if action.cat == "snap": self.snap_and_rec(obstacle_id=action.value)
            elif action.cat == "stitch": self.request_stitch()

    def snap_and_rec(self, obstacle_id: str) -> None:
        """
        RPi snaps an image and calls the API for image-rec.
        The response is then forwarded back to the android
        :param obstacle_id: the current obstacle ID
        """
        
        
        self.logger.info(f"Capturing image for obstacle id: {obstacle_id}")
        self.android_queue.put(AndroidMessage(
            "info", f"Capturing image for obstacle id: {obstacle_id}"))
        url = f"http://{IMG_IP}:{IMG_PORT}/predict_week9"
        filename = f"{int(time.time())}_{obstacle_id}.jpg"
        
        image_folder = "captured_images/"
        annotated_folder = "annotated_images/"

        if not os.path.exists(image_folder):
            os.makedirs(image_folder)
        if not os.path.exists(annotated_folder):
            os.makedirs(annotated_folder)
        image_path = os.path.join(image_folder, filename)   
        retry_count = 0
        while True:
            retry_count += 1
            camera = PiCamera()
            camera.resolution = (520,520)
            camera.brightness = 65
            camera.contrast = 75
            camera.sharpness = 100


            # Start the camera and take a picture
            camera.capture(image_path)
            camera.close()

            self.logger.debug("Requesting from image API")
            with open(image_path, 'rb') as file:
                files = {'file': (filename, file)}
                response = requests.post(url, files=files)
                data = response.json()
                x1 = data[0].get("x1")
                x2 = data[0].get("x2")
                y1 = data[0].get("y1")
                y2 = data[0].get("y2")
                label = data[0].get("class_name")
                obs_id = data[0].get("class_id")
            if obs_id != 'NA' or retry_count > 2:
                break
            self.logger.debug("Image recognition error, recapturing...")
            
            
        with Image.open(image_path) as img:
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf",50)
            except IOError:
                print("cannot find font")
                font = ImageFont.load_default()
            draw = ImageDraw.Draw(img)
            draw.rectangle([x1,y1,x2,y2], outline='red', width=3)
            text_w, text_h = draw.textsize(label, font = font)
            text_position = (x1 + 5, y1 - text_h - 10)
            draw.text(text_position, label, fill='red', font=font)
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(annotated_folder, f"image_{current_time}_{label}.jpg")
            img.save(save_path)
            #img.show()
        
        results = {"image_id" : obs_id,"obstacle_id" : obstacle_id}
           # 

        
            
            
            
        self.logger.info(f"Image recognition results: ({label})")
        return label

    def request_stitch(self):
          # Initialize path to save stitched image
        imgFolder = 'runs'
        annotated_folder = "~/shared/sc2079group44rpi/annotated_images/"
        stitchedPath = os.path.join(annotated_folder, f'stitched-{int(time.time())}.jpeg')
        #annotated_folder = "/shared/annotated_images"

        imgPaths = glob.glob(os.path.join(annotated_folder, "*.jpg"))
        # Open all images
        images = [Image.open(x) for x in imgPaths]
        # Get the width and height of each image
        width, height = zip(*(i.size for i in images))
        # Calculate the total width and max height of the stitched image, as we are stitching horizontally
        total_width = sum(width)
        max_height = max(height)
        stitchedImg = Image.new('RGB', (total_width, max_height))
        x_offset = 0

        # Stitch the images together
        for im in images:
            stitchedImg.paste(im, (x_offset, 0))
            x_offset += im.size[0]
        # Save the stitched image to the path
        stitchedImg.save(stitchedPath)

        self.logger.info("Images stitched!")
        self.android_queue.put(AndroidMessage("info", "Images stitched!"))
        
    def clear_queues(self):
        while not self.command_queue.empty():
            self.command_queue.get()

    def check_api(self) -> bool:
        url = f"http://{IMG_IP}:{IMG_PORT}/status"
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                self.logger.debug("API is up!")
                return True
        except ConnectionError:
            self.logger.warning("API Connection Error")
            return False
        except requests.Timeout:
            self.logger.warning("API Timeout")
            return False
        except Exception as e:
            self.logger.warning(f"API Exception: {e}")
            return False

if __name__ == "__main__":
    rpi = RaspberryPi()
    rpi.start()
