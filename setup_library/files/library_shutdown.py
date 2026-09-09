#!/usr/bin/python3
from flask import Flask, render_template_string, request
import subprocess
import socket
import os

app = Flask(__name__)

# Function to check if the port is already in use
def check_port(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))  # Try to bind to the port
            s.close()  # Close the socket if the bind is successful
            return True
        except socket.error:
            return False

# HTML template string with styles for the curved box and button
html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Shutdown Library</title>
<style>
    body {
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100vh;
        margin: 0;
        background-color: #000000;
    }
    .curved-box {
        text-align: center;
        padding: 2em;
        border-radius: 15px;
        background: #ddd;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }
    .shutdown-btn {
        font-size: 1em;
        padding: 0.5em 1em;
        color: white;
        background-color: #e51000;
        border: none;
        border-radius: 5px;
        cursor: pointer;
    }
</style>
</head>
<body>
    <div class="curved-box">
        <form action="{{ url_for('shutdown') }}" method="post">
            <h1>Are you sure you want to shut down?</h1>
            <p>Once clicked there will be no respone until system is stopping.
            <button type="submit" class="shutdown-btn">Shutdown</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(html_template)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    try:
        subprocess.run(['/usr/local/bin/library_shutdown'], check=True)
        shutdown_message = "The library is now shutting down."
    except subprocess.CalledProcessError as e:
        shutdown_message = "Failed to shutdown the library. Error: {}".format(e)
    return "<center><h1>{}</h1></center>".format(shutdown_message)

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 9999
    if check_port(host, port):
        app.run(port=port, host=host)
    else:
        print(f"Another process is already listening on port {port}.")
        os._exit(1)  # Exit without cleanup if port is in use
