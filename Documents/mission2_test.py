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
    # BACKWARD_LEFT: 1.65
    # BACKWARD_RIGHT: 1.65

    # Distance to set of accurate turns (speed = 1000)
    # NEW USE THIS
    # FORWARD_RIGHT: 70
    # FORWARD_LEFT: 60
    # BACKWARD_RIGHT: 70.0
    # BACKWARD_LEFT: 50.0
    # Queue the test states

    # Distance to set of accurate turns (speed = 2000)
    # FORWARD_RIGHT: 70
    # FORWARD_LEFT: 65
    # BACKWARD_RIGHT: 64.0
    # BACKWARD_LEFT: 43.0
    # Queue the test states


    queue_state_transition("FP_1", 2500, 100, 50)
    wait_to_send()
    first_obs = 0
    if (first_obs == 1): #left
        queue_state_transition("FORWARD_TURN", 1500, 40, 25)
        queue_state_transition("FORWARD", 1000, 25, 0)
        queue_state_transition("FORWARD_TURN", 1500, -120, 60)
        queue_state_transition("FORWARD_TURN", 1000, -20, 10)
        queue_state_transition("FORWARD_TURN", 1000, 55, 30)
        queue_state_transition("FP_1", 2500, 150, 35)
    else: #right
        queue_state_transition("FORWARD_TURN", 1500, -40, 30)
        queue_state_transition("FORWARD", 1000, 30, 0)
        queue_state_transition("FORWARD_TURN", 1500, 100, 40)
        queue_state_transition("FORWARD", 1000, 15, 0)
        #queue_state_transition("FORWARD_TURN", 1000, 20, 15)
        queue_state_transition("FORWARD_TURN", 1000, -100, 35)
        queue_state_transition("FP_1", 2500, 100, 35)
    for _ in range(6):
        wait_to_send()
    second_obs = 0
    if (second_obs == 1):
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("FORWARD_UPO", 1500, 100, 0)
        queue_state_transition("BACKWARD", 2000, 10, 0)
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("FORWARD_UPO", 1500, 100, 0)
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("FP_2", 2000, 0, 80)
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("BACKWARD", 2000, 40, 0)
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("FP_1", 1000, 100, 15)
    else:
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("FORWARD_UPO", 1500, 100, 1)
        #queue_state_transition("BACKWARD", 2000, 10, 0)
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("FORWARD_UPO", 1500, 100, 1)
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("FP_2", 2000, 0, 80)
        queue_state_transition("FORWARD_LEFT", 1000, 60, 0)
        queue_state_transition("BACKWARD", 2000, 40, 0)
        queue_state_transition("FORWARD_RIGHT", 1000, 70, 0)
        queue_state_transition("FP_1", 1000, 100, 15)
    for _ in range(12):
        wait_to_send()
    while not stop_thread.is_set():
        time.sleep(1)

finally:
    stop_thread.set()
    thread.join()
    ser.close()
