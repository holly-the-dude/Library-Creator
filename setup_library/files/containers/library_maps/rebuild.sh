podman stop library_maps
podman rmi --force localhost/library_maps
podman build -t library_maps .
# Match the appliance's USB discovery/hotplug access; run rootfully on Linux.
# Binding /dev keeps later USB attachments visible; never add :z or :Z here.
# GPS settings come from exported shell variables (this script does not load
# compose's .env); 9600 is the default baud.
#
# GPS_PORT defaults to the u-blox receiver's persistent by-id path. Pinning it
# is required on this appliance: the Meshtastic container also exposes a generic
# CP2102 serial device, and empty-port auto-detection would otherwise claim that
# radio and fight its bridge for the port. Override GPS_PORT for a different
# receiver, or set it empty to re-enable discovery on a maps-only host.
# The graphhopper host entry lets nginx resolve routing even when it is offline.
podman run -d --name library_maps --replace --privileged --restart unless-stopped \
  --add-host graphhopper:10.88.0.213 -v /dev:/dev \
  -e GPS_PORT="${GPS_PORT:-/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00}" \
  -e GPS_BAUD="${GPS_BAUD:-9600}" \
  -p 8080:8080 -v /Library/maps:/storage/maps localhost/library_maps:latest
