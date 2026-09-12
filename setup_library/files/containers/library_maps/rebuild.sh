podman stop library_maps
podman rmi --force localhost/library_maps
podman build -t library_maps .
# Match the appliance's USB discovery/hotplug access; run rootfully on Linux.
# Binding /dev keeps later USB attachments visible; never add :z or :Z here.
# GPS settings come from exported shell variables (this script does not load
# compose's .env); an empty port enables discovery and 9600 is the default baud.
# The graphhopper host entry lets nginx resolve routing even when it is offline.
podman run -d --name library_maps --replace --privileged --restart unless-stopped \
  --add-host graphhopper:10.88.0.213 -v /dev:/dev \
  -e GPS_PORT="${GPS_PORT:-}" -e GPS_BAUD="${GPS_BAUD:-9600}" \
  -p 8080:8080 -v /Library/maps:/storage/maps localhost/library_maps:latest
