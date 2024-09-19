import serial
import threading
import time
from queue import Queue

# Scale to set
# FORWARD_TURN: 1.7
# FORWARD_LEFT: 1.7
# FORWARD_RIGHT: 1.7
# BACKWARD_LEFT: 1.5
# BACKWARD_RIGHT: 1.5

# Distance to set of accurate turns
# FORWARD_LEFT: 65.0
# FORWARD_RIGHT: 70.0
# BACKWARD_LEFT: 50.0
# BACKWARD_RIGHT: 57.0

# Lists of commands
# FORWARD
# FORWARD_TURN
# FORWARD_LEFT
# FORWARD_RIGHT
# BACKWARD
# BACKWARD_RIGHT
# BACKWARD_LEFT
# Note that the value of motorspeed will not matter for FORWARD_LEFT/RIGHT & BACKWARD_LEFT/RIGHT as the values have been hardcoded

SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout = 1)

stop_thread = threading.Event()

state_queue = Queue()

# Try sending the state when received the current state starting, to reduce time taken to transit to next state next time

def receive_thread():
    while not stop_thread.is_set():
        if ser.in_waiting > 0:
            message = ser.readline().decode('utf-8').strip()

            if message == '0':
                print("Received 0 : Previous state completed")

                if not state_queue.empty():
                    next_state = state_queue.get()
                    send_message(*next_state)

            elif message == '1':
                print("Received 1 : Current state starting")
            else:
                handle_received_message(message)

# For future use i guess
def handle_received_message(message):
    print(f"Received: {message}")

def send_message(state, motor_speed, param, scale):
    message = f"{state} {motor_speed} {param} {scale}"
    
    padded_message = message.ljust(30)

    ser.write(padded_message.encode())

    print(f"Sent : {padded_message.strip()}")

def queue_state_transition(state, motor_speed, param, scale):
    state_queue.put((state, motor_speed, param, scale))



try:
    #start the receiving thread
    thread = threading.Thread(target=receive_thread)
    thread.start()

    # Queue the test states
    #queue_state_transition("FORWARD_TURN", 3000, -270.0, 1.7)
    #queue_state_transition("FORWARD", 3000, 100.0)
    #time.sleep(1)
    #queue_state_transition("FORWARD_LEFT", 3000, 65.0, 1.7)
    #time.sleep(1)
    #queue_state_transition("FORWARD_RIGHT", 3000, 70.0, 1.7)
    #time.sleep(1)
    #queue_state_transition("FORWARD_RIGHT", 3000, 65.0)
    #time.sleep(1)
    #queue_state_transition("FORWARD_RIGHT", 3000, -90.0)
    #time.sleep(1)
    #queue_state_transition("FORWARD", 3000, 50.0)
    #time.sleep(1)
    #queue_state_transition("BACKWARD_LEFT", 3000, 70.0, 1.5)
    #time.sleep(1)
    #queue_state_transition("FORWARD", 3000, 70.0)
    #time.sleep(1)
    #queue_state_transition("BACKWARD_RIGHT", 3000, 57.0, 1.5)
    #time.sleep(1)
    queue_state_transition("FORWARD", 3000, 70.0, 0)
    time.sleep(1)
    queue_state_transition("FORWARD_RIGHT", 3000, 70, 1.7)
    time.sleep(1)
    queue_state_transition("FORWARD", 3000, 40.0, 0)
    time.sleep(1)
    queue_state_transition("FORWARD_RIGHT", 3000, 70, 1.7)
    time.sleep(1)
    queue_state_transition("FORWARD", 3000, 30.0, 0)
    time.sleep(1)
    queue_state_transition("FORWARD_RIGHT", 3000, 70, 1.7)
    time.sleep(1)
    queue_state_transition("FORWARD", 3000, 20, 0)
    time.sleep(1)
    queue_state_transition("BACKWARD_LEFT", 2000, 50.0, 1.5)
    
    while not stop_thread.is_set():
        time.sleep(1)

finally:
    stop_thread.set()
    thread.join()
    ser.close()
