#!/bin/bash

apt list --installed 2>/dev/null|grep samba && echo "Samba Installed" || apt-get -y install samba samba-common-bin


# Define the directory to share
DIRECTORY="/Library/library"

# Check if the directory exists
if [ -d "$DIRECTORY" ]; then
    # Directory exists, set up the Samba share

    # Add configuration to the smb.conf file
    echo "[Library]
    public = yes
    force user = root
    only guest = no
    path = $DIRECTORY
    browseable = yes
    read only = no
    writable = yes
    guest ok = yes
    guest only = yes
    create mask = 0775
    directory mask = 0775" | sudo tee -a /etc/samba/smb.conf

    # Restart Samba to apply changes
    sudo systemctl restart smbd

    echo "Samba share for $DIRECTORY has been created."
else
    # Directory does not exist
    echo "Directory $DIRECTORY does not exist. No share created."
fi
