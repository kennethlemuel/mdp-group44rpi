import json
import time
from multiprocessing import Process, Manager
from typing import Optional
from queue import Empty
import requests
from usb_interface_upd import send_message, queue_state_transition, stop_thread, ser
from communication.android import AndroidLink, AndroidMessage
from consts import SYMBOL_MAP
from logger import prepare_logger
from settings import API_IP, API_PORT

class RaspberryPi:
    """
    Class that represents the Raspberry Pi.
    """

    def __init__(self):
        """
        Initializes the Raspberry Pi.
        """
        self.logger = prepare_logger()
        self.android_link = AndroidLink()
        
        self.manager = Manager()

        self.android_dropped = self.manager.Event()
        self.unpause = self.manager.Event()

        self.movement_lock = self.manager.Lock()

        self.android_queue = self.manager.Queue()  # Messages to send to Android
        # Messages that need to be processed by RPi
        self.rpi_action_queue = self.manager.Queue()
        # Messages that need to be processed by STM32, as well as snap commands
        self.command_queue = self.manager.Queue()
        # X,Y,D coordinates of the robot after execution of a command
        self.path_queue = self.manager.Queue()

        self.proc_recv_android = None
        self.proc_recv_stm32 = None
        self.proc_android_sender = None
        self.proc_command_follower = None
        self.proc_rpi_action = None
        self.rs_flag = False
        self.success_obstacles = self.manager.list()
        self.failed_obstacles = self.manager.list()
        self.obstacles = self.manager.dict()
        self.current_location = self.manager.dict()
        self.failed_attempt = False

    def start(self):
        """Starts the RPi orchestrator"""
        try:
            ### Start up initialization ###
            self.android_link.connect()
            self.android_queue.put(AndroidMessage(
                'info', 'You are connected to the RPi!'))

            self.check_api()

            # Start the USB interface receive thread
            self.proc_recv_stm32 = Process(target=self.recv_stm)
            self.proc_recv_stm32.start()

            # Define child processes
            self.proc_recv_android = Process(target=self.recv_android)
            self.proc_android_sender = Process(target=self.android_sender)
            self.proc_command_follower = Process(target=self.command_follower)
            self.proc_rpi_action = Process(target=self.rpi_action)

            # Start child processes
            self.proc_recv_android.start()
            self.proc_android_sender.start()
            self.proc_command_follower.start()
            self.proc_rpi_action.start()

            self.logger.info("Child Processes started")

            ### Start up complete ###

            # Send success message to Android
            self.android_queue.put(AndroidMessage('info', 'Robot is ready!'))
            self.android_queue.put(AndroidMessage('mode', 'path'))
            self.reconnect_android()

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stops all processes on the RPi and disconnects gracefully with Android and STM32"""
        # Stop all child processes
        if self.proc_recv_android:
            self.proc_recv_android.terminate()
        if self.proc_recv_stm32:
            stop_thread.set()  # Signal the USB interface thread to stop
        if self.proc_android_sender:
            self.proc_android_sender.terminate()
        if self.proc_command_follower:
            self.proc_command_follower.terminate()
        if self.proc_rpi_action:
            self.proc_rpi_action.terminate()

        # Disconnect Android and STM32
        self.android_link.disconnect()
        ser.close()
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
            self.android_queue.put(AndroidMessage(
                "info", "You are reconnected!"))
            self.android_queue.put(AndroidMessage('mode', 'path'))

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

            if msg_str is None:
                continue

            message: dict = json.loads(msg_str)

            ## Command: Set obstacles ##
            if message['cat'] == "obstacles":
                self.rpi_action_queue.put(PiAction(**message))
                self.logger.debug(
                    f"Set obstacles PiAction added to queue: {message}")

            ## Command: Start Moving ##
            elif message['cat'] == "control":
                if message['value'] == "start":
                    # Check API
                    if not self.check_api():
                        self.logger.error(
                            "API is down! Start command aborted.")
                        self.android_queue.put(AndroidMessage(
                            'error', "API is down, start command aborted."))

                    # Commencing path following
                    if not self.command_queue.empty():
                        self.logger.info("Gryo reset!")
                        queue_state_transition("RS00", 0, 0, 0)
                        # Main trigger to start movement #
                        self.unpause.set()
                        self.logger.info(
                            "Start command received, starting robot on path!")
                        self.android_queue.put(AndroidMessage(
                            'info', 'Starting robot on path!'))
                        self.android_queue.put(
                            AndroidMessage('status', 'running'))
                    else:
                        self.logger.warning(
                            "The command queue is empty, please set obstacles.")
                        self.android_queue.put(AndroidMessage(
                            "error", "Command queue is empty, did you set obstacles?"))

    def recv_stm(self) -> None:
        """
        [Child Process] Receive acknowledgement messages from STM32, and release the movement lock
        """
        while not stop_thread.is_set():
            try:
                message = ser.readline().decode('utf-8').strip()
                if message.startswith("ACK"):
                    if self.rs_flag == False:
                        self.rs_flag = True
                        self.logger.debug("ACK for RS00 from STM32 received.")
                        continue
                    try:
                        self.movement_lock.release()
                        self.logger.debug(
                            "ACK from STM32 received, movement lock released.")

                        cur_location = self.path_queue.get_nowait()
                        self.current_location['x'] = cur_location['x']
                        self.current_location['y'] = cur_location['y']
                        self.current_location['d'] = cur_location['d']
                        self.logger.info(
                            f"self.current_location = {self.current_location}")
                        self.android_queue.put(AndroidMessage('location', {
                            "x": cur_location['x'],
                            "y": cur_location['y'],
                            "d": cur_location['d'],
                        }))

                    except Empty:
                        self.logger.warning("Tried to release a released lock!")
                else:
                    self.logger.warning(
                        f"Ignored unknown message from STM: {message}")
            except Exception as e:
                self.logger.error(f"Error reading from STM: {e}")

    def android_sender(self) -> None:
        """
        [Child process] Responsible for retrieving messages from android_queue and sending them over the Android link. 
        """
        while True:
            # Retrieve from queue
            try:
                message: AndroidMessage = self.android_queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                self.android_link.send(message)
            except OSError:
                self.android_dropped.set()
                self.logger.debug("Event set: Android dropped")

    def command_follower(self) -> None:
        """
        [Child Process] Executes commands in the command queue
        """
        while True:
            # Retrieve next movement command
            command: str = self.command_queue.get()
            self.logger.debug("wait for unpause")
            # Wait for unpause event to be true [Main Trigger]
            try:
                self.unpause.wait()
            except Exception:
                self.logger.debug("wait for unpause error")
            self.logger.debug("wait for movelock")
            # Acquire lock first (needed for both moving, and snapping pictures)
            self.movement_lock.acquire()

            # STM32 Commands - Send straight to STM32
            stm32_prefixes = ("FS", "BS", "FW", "BW", "FL", "FR", "BL",
                              "BR", "TL", "TR", "A", "C", "DT", "STOP", "ZZ", "RS")
            if command.startswith(stm32_prefixes):
                queue_state_transition(command, 0, 0, 0)

    def rpi_action(self):
        """
        [Child Process] 
        """
        while True:
            action: PiAction = self.rpi_action_queue.get()
            self.logger.debug(
                f"PiAction retrieved from queue: {action.cat} {action.value}")

            if action.cat == "obstacles":
                for obs in action.value['obstacles']:
                    self.obstacles[obs['id']] = obs
                self.request_algo(action.value)
            elif action.cat == "snap":
                self.snap_and_rec(obstacle_id_with_signal=action.value)
            elif action.cat == "stitch":
                self.request_stitch()

if __name__ == "__main__":
    rpi = RaspberryPi()
    rpi.start()
