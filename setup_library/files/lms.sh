docker pull epoupon/lms
podman run -d  --rm --name=music --user 0 --privileged -p 9099:5082 -v /Library/music/:/music/:ro -v /Library/.music_data:/var/lms  music:latest
podman stop music
podman volume rm --all --force
# sqlite force a password of just music 
# htpasswd -bnBC 10 "" music| tr -d ':\n' | sed 's/$2y/$2a/'
# note sthe 10 is the salt 
#
# sqlite /Library/.music_data/lms.db
# .quit 
UPDATE user SET password_salt="10", password_hash="$2a$10$mOfncvobmbvX2iTR1d4oD.pebrvBSXVfO4q4cyOwUNDk2fDCTCA1S" WHERE id=1;
podman volume rm --all --force
