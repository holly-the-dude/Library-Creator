rm rasbase.tar 2>/dev/null
cat rasbase?? >>rasbase.tar

podman load -i rasbase.tar
