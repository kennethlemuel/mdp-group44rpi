import serial
import threading
import time
from queue import Queue
import random

SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout = 1)

stop_thread = threading.Event()

state_queue = Queue()

ready_to_send = True 
ready_to_send_lock = threading.Lock()

def receive_thread():
    global ready_to_send
    while not stop_thread.is_set():
        if ser.in_waiting > 0:
            message = ser.readline().decode('utf-8').strip()

            if message == '0':
                print("Received 0 : Previous state completed")
                with ready_to_send_lock:
                    ready_to_send = True
                #if not state_queue.empty():
                #    next_state = state_queue.get()
                #   send_message(*next_state)

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

    #ready_to_send = False

    print(f"Sent : {padded_message.strip()}")


def queue_state_transition(state, motor_speed, param, scale):
    state_queue.put((state, motor_speed, param, scale))

def wait_to_send():
    global ready_to_send
    while True:
        with ready_to_send_lock:
            if ready_to_send:
                break
        time.sleep(1)
    with ready_to_send_lock:
        ready_to_send = False
    if not state_queue.empty():
        send_message(*(state_queue.get()))


try:
    #start the receiving thread
    thread = threading.Thread(target=receive_thread)
    thread.start()

    # Scale to set
    # FORWARD_TURN: 1.8 (R) 1.7 (L) 
    # FORWARD_LEFT: 1.75
    # FORWARD_RIGHT: 1.75
    # BACKWARD_LEFT: 1.TURN_DIST
    # BACKWARD_RIGHT: 1.TURN_DIST

    # Distance to set of accurate turns (speed = 1000)
    # NEW USE THIS
    # FORWARD_RIGHT: 70
    # FORWARD_LEFT: 60
    # BACKWARD_RIGHT: 70.0
    # BACKWARD_LEFT: 50.0
    # Queue the test states

    # Distance to set of accurate turns (speed = SPEED)
    # FORWARD_RIGHT: 70
    # FORWARD_LEFT: TURN_DIST
    # BACKWARD_RIGHT: TURN_DIST.0
    # BACKWARD_LEFT: 43.0
    # Queue the test states
    LEFT = 1
    RIGHT = 0
    SPEED = 3000
    TURN_DIST = 65

    queue_state_transition("FP_1", SPEED, 200, 40)
    wait_to_send()
    first_obs = RIGHT
    if (first_obs == LEFT): #left
        queue_state_transition("FORWARD_TURN", 2000, 45, 30)
        queue_state_transition("FORWARD", 1000, 15, 0)
        queue_state_transition("FORWARD_TURN", 2000, -45, 30)
        queue_state_transition("FORWARD", 2000, 5, 0)
        queue_state_transition("FORWARD_TURN", 2000, -45, 30)
        queue_state_transition("FORWARD_TURN", 2000, 45, 30)
        queue_state_transition("FP_1", SPEED, 200, 30)
    else: #right
        queue_state_transition("FORWARD_TURN", 2000, -45, 30)
        queue_state_transition("FORWARD", 1000, 15, 0)
        queue_state_transition("FORWARD_TURN", 2000, 45, 30)
        queue_state_transition("FORWARD", 2000, 5, 0)
        queue_state_transition("FORWARD_TURN", 2000, 45, 30)
        queue_state_transition("FORWARD_TURN", 2000, -45, 30)
        queue_state_transition("FP_1", SPEED, 200, 30)
 
    for _ in range(7):
       wait_to_send()

    second_obs = LEFT
    if (second_obs == LEFT):
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("FORWARD_UPO", 2000, 40, RIGHT)
        queue_state_transition("FORWARD", 2000, 10, 0)
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("FORWARD_UDO", 2000, 40, RIGHT)
        queue_state_transition("FORWARD_UPO", 2000, 40, RIGHT)
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("FP_2", 3000, 0, 60)
        queue_state_transition("FORWARD", 2000, 10, 0)
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("BACKWARD", 2000, 30, 0)
        queue_state_transition("FORWARD_UDO", 2000, 30, RIGHT)
        queue_state_transition("BACKWARD", 2000, 20, 0)
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("FP_1", 2000, 100, 20)
    else:
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("FORWARD_UPO", 2000, 40, LEFT)
        queue_state_transition("FORWARD", 2000, 10, 0)
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("FORWARD_UDO", 2000, 40, LEFT)
        queue_state_transition("FORWARD_UPO", 2000, 40, LEFT)
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("FP_2", 3000, 0, 60)
        queue_state_transition("FORWARD", 2000, 20, 0)
        queue_state_transition("FORWARD_LEFT2", 3000, 70, 0)
        queue_state_transition("BACKWARD", 2000, 30, 0)
        queue_state_transition("FORWARD_UDO", 2000, 40, LEFT)
        queue_state_transition("BACKWARD", 2000, 20, 0)
        queue_state_transition("FORWARD_RIGHT2", 3000, 70, 0)
        queue_state_transition("FP_1", 2000, 100, 15)


    for _ in range(19):
        wait_to_send()
    while not stop_thread.is_set():
        time.sleep(1)

finally:
    stop_thread.set()
    thread.join()
    ser.close()
