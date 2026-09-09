#!/usr/bin/python3

import os
import time
import cgi
import cgitb; cgitb.enable()  # Enable debugging

print("Content-type: text/html\n\n")
print("<html><body><h1>Shutting down...</h1></body></html>")

time.sleep(4)
os.system('echo "shutdown -P now" | at now +0 minute')
os.system('podman stop $(podman ps -aq)')

