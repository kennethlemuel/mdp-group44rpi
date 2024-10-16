
from typing import Optional
import serial
from communication.link import Link
from settings import SERIAL_PORT, BAUD_RATE


class STMLink(Link):
    """Class for communicating with STM32 microcontroller over UART serial connection.

    ### RPi to STM32
    RPi sends the following commands to the STM32.

    #### Path mode commands
    High speed forward/backward, with turning radius of `3x1`
    - `FW0x`: Move forward `x` units
    - `BW0x`: Move backward `x` units
    - `FL00`: Move to the forward-left location
    - `FR00`: Move to the forward-right location
    - `BL00`: Move to the backward-left location
    - `BR00`: Move to the backward-right location

    #### Manual mode commands
    - `FW--`: Move forward indefinitely
    - `BW--`: Move backward indefinitely
    - `TL--`: Steer left indefinitely
    - `TR--`: Steer right indefinitely
    - `STOP`: Stop all servos

    ### STM32 to RPi
    After every command received on the STM32, an acknowledgement (string: `ACK`) must be sent back to the RPi.
    This signals to the RPi that the STM32 has completed the command, and is ready for the next command.

    """

    def __init__(self):
        """
        Constructor for STMLink.
        """
        super().__init__()
        self.serial_link = None

    def connect(self):
        """Connect to STM32 using serial UART connection, given the serial port and the baud rate"""
        self.serial_link = serial.Serial(SERIAL_PORT, BAUD_RATE)
        self.logger.info("Connected to STM32")

    def disconnect(self):
        """Disconnect from STM32 by closing the serial link that was opened during connect()"""
        self.serial_link.close()
        self.serial_link = None
        self.logger.info("Disconnected from STM32")

    def send(self, message: str) -> None:
        """Send a message to STM32, utf-8 encoded 
        Args:
            message (str): message to send
        """

        self.logger.info("Entered")
        parsed_result = self.parse_message(message)
        message = f"{parsed_result.get('action')} {parsed_result.get('motorspeed')} {parsed_result.get('param')} {parsed_result.get('scale')}"
        padded_message = message.ljust(30)
        self.serial_link.write(padded_message.encode("utf-8"))
        self.logger.debug(f"Sent to STM32: {padded_message}")

    def send_week9(self, message: list) -> None:
        self.logger.info("Entered")
        message = f"{message[0]} {message[1]} {message[2]} {message[3]}"
        padded_message = message.ljust(30)
        self.serial_link.write(padded_message.encode("utf-8"))
        self.logger.debug(f"Sent to STM32: {padded_message}")

    def recv(self) -> Optional[str]:
        """Receive a message from STM32, utf-8 decoded

        Returns:
            Optional[str]: message received
        """
        message = self.serial_link.readline().strip().decode("utf-8")
        self.logger.debug(f"Received from STM32: {message}")
        return message

    def parse_message(self, message: str):
        actions = {
            "FW": "FP_1",
            "BW": "BACKWARD",
            "FL": "FORWARD_LEFT2",
            "FR": "FORWARD_RIGHT2",
            "BL": "BACKWARD_LEFT2",
            "BR": "BACKWARD_RIGHT2"
        }

        motor_speeds = {
            "FW": 2000,
            "BW": 2000,
            "FL": 3000,
            "FR": 3000,
            "BL": 3000,
            "BR": 3000
        }

        scales = {
            "FW": 10,
            "BW": 0,
            "FL": 0,
            "FR": 0,
            "BL": 0,
            "BR": 0
        }

        params = {
            "FL": 70.0,
            "FR": 70.0,
            "BL": 70.0,
            "BR": 70.0
        }

        action = None
        motorspeed = None
        param = None
        scale = None

        for key in actions:
            if message.startswith(key):
                action = actions[key]
                motorspeed = motor_speeds[key]  # Corrected from `motorspeed[key]`
                scale = scales[key]
                if key == "FL" or key == "FR" or key == "BL" or key == "BR":  # Corrected `=` to `==`
                    param = params[key]
                else:
                    param = message[len(key):]  # Extracts remaining message part

        return {"action": action, "motorspeed": motorspeed, "param": param, "scale": scale}


