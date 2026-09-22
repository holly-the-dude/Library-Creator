#!/bin/sh
set -eu
export TERM="${TERM:-xterm-256color}"
# Take over the existing session, including an in-progress flash, from web/SSH.
exec tmux -L meshflash attach-session -d -t flash
