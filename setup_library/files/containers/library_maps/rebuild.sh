podman stop library_maps
podman rmi --force localhost/library_maps
podman build -t library_maps .
podman run -d --name library_maps --replace -p 8080:8080 -v /Library/maps:/storage/maps  localhost/library_maps:latest

