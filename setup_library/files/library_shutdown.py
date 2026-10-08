#!/usr/bin/python3
"""Serve the host's shutdown/restart confirmation page on port 9999.

POST /shutdown runs the existing power-off helper. POST /reboot schedules the
graceful library-restart.service so its sequence survives the HTTP connection.
Opening the page with GET never changes the host's power state.
"""
from flask import Flask, render_template_string
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
<title>Shutdown or Restart Library</title>
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
    .restart-btn { background-color: #2463a6; }
</style>
</head>
<body>
    <div class="curved-box">
        <form action="{{ url_for('shutdown') }}" method="post">
            <h1>Are you sure you want to shut down?</h1>
            <p>Wait for shutdown to finish before disconnecting power.</p>
            <button type="submit" class="shutdown-btn">Shutdown</button>
        </form>
        <form action="{{ url_for('reboot') }}" method="post">
            <h1>Restart the Library?</h1>
            <p>Finish downloads first. Restart stops containers gracefully and
               starts the Library again. Keep power connected.</p>
            <button type="submit" class="shutdown-btn restart-btn">Restart</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(html_template)

@app.route('/reboot', methods=['POST'])
def reboot():
    """Schedule the host restart independently of this web request."""
    try:
        subprocess.run(['/usr/bin/systemctl', '--no-block', 'start',
                        'library-restart.service'], check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        app.logger.exception("Could not schedule Library restart")
        return "<h1>Could not start the restart service.</h1><p>Check the host service logs and try again.</p>", 503
    return ("<h1>The Library restart has been scheduled.</h1>"
            "<p>Keep power connected. Reconnect to Library Wi-Fi and reopen the "
            "Library page when startup finishes.</p>"), 202


@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Run the existing graceful power-off helper."""
    try:
        subprocess.run(['/usr/local/bin/library_shutdown'], check=True)
        shutdown_message = "The library is now shutting down."
    except (OSError, subprocess.SubprocessError):
        app.logger.exception("Could not shut down Library")
        return "<h1>Could not shut down the Library.</h1><p>Check the host service logs and try again.</p>", 503
    return "<center><h1>{}</h1></center>".format(shutdown_message)

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 9999
    if check_port(host, port):
        app.run(port=port, host=host)
    else:
        print(f"Another process is already listening on port {port}.")
        os._exit(1)  # Exit without cleanup if port is in use
