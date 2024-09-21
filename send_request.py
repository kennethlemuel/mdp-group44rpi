import json
import requests

# API settings
API_IP = '127.0.0.1'  # Replace with the actual IP address of your laptop.
API_PORT = 5000  # Replace with the correct port number if different.

# Read the JSON file
with open('path_request.json', 'r') as file:
    data = json.load(file)

# Define the API endpoint
url = "http://{API_IP}:{API_PORT}/path".format(API_IP,API_PORT)

try:
    # Send POST request to the API
    response = requests.post(url, json=data)
    
    # Check if the request was successful
    if response.status_code == 200:
        print("Request was successful!")
        print("Received response from API:")
        print(response.json())
    else:
        print("Failed to get response from API, Status Code:".format(response.status_code))
        print(response.text)

except requests.exceptions.RequestException as e:
    print("Error while sending request:".format(e))