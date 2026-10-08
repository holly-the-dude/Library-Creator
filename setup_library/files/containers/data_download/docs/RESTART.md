# Restarting after downloads

The completion popup offers **Restart Library** and **I'll restart later**.
Restart stops containers gracefully and reboots automatically. Keep power
connected, even during the “OK to power off” splash. Reconnect to Library Wi-Fi
and reload the page after startup. Routing imports need extra startup time.

For routing, dismiss the popup first and choose **Use after restart** beside the
downloaded region. Reopen the downloader page to see the reminder again, then
restart. Downloading a routing file alone does not activate it.

Restart is refused while a job is queued, downloading, verifying, or extracting.
Once a restart is accepted, new downloads are refused. Completing a download
never reboots automatically. If the button is disabled because the host handler
is missing, use the existing Shutdown option and turn the Library back on after
shutdown finishes.

## Installation and upgrades

New installations use `setup_library/01_install_ansible.yml` to install the host
files and enable `library-control.socket`. The updated startup playbook mounts
the control directory only when its socket exists. Rebuild the downloader image
and recreate the container to include the button and mount.

For an existing Pi, copy these files from `setup_library/files` to the host:

| Repository file | Host destination | Mode |
| --- | --- | --- |
| `library_restart` | `/usr/local/bin/library_restart` | `0755` |
| `library_control.py` | `/usr/local/bin/library_control.py` | `0755` |
| `library-control.socket` | `/etc/systemd/system/library-control.socket` | `0644` |
| `library-control.service` | `/etc/systemd/system/library-control.service` | `0644` |
| `library-restart.service` | `/etc/systemd/system/library-restart.service` | `0644` |

Then run as root on the Pi:

```sh
systemctl daemon-reload
systemctl enable --now library-control.socket
```

Deploy the updated startup playbook to `/root/start_library.yml`, install the
rebuilt downloader image, and recreate its container. Enabling the socket does
not request a restart. Do **not** start `library-restart.service` for installation;
starting it performs the restart.

Standalone rootful Podman/Compose users can opt in after installing these files
by adding `/run/library-control:/run/library-control:ro` to the downloader's
volume mounts. Default Compose remains usable on hosts without this service.

## Host implementation

The host's existing port-9999 power page (`library_shutdown.py`) also has a
Restart button. Its POST `/reboot` schedules the same service; POST `/shutdown`
continues to use the power-off helper. Opening either action with GET cannot
change power state. Unlike the downloader API, this separate power page does not
check the download queue, so finish downloads before using its buttons.

To verify the power-page routes without changing host power state, run from the
repository root in a Python environment with Flask installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s setup_library/tests -p test_library_shutdown.py -v
```

All host commands in this test are mocked.

`library_control.py` is a standard-library Python server. Systemd supplies its
listening Unix socket on descriptor 3. It accepts only `restart\n`, and responds
`OK\n` when systemd accepts the fixed `library-restart.service` job, or
`ERROR ...\n` on failure. It accepts no shell commands or caller-supplied arguments.
The socket and directory are root-only, with no TCP listener. The downloader
mounts the directory read-only and needs no Podman socket or privileged mode.

The service waits two seconds for the browser response, then runs the host's
`library_restart` independently of the downloader container:

1. Source `/root/.profile`.
2. Display `library_shutting_down.jpg`, then wait two seconds.
3. Run `/usr/bin/podman stop --all --time 30`, allowing containers to exit before
   Podman forces termination after the timeout.
4. Display `library_ok_to_poweroff.jpg`, then wait two seconds.
5. Run `/usr/sbin/shutdown -r now`.

If Podman reports a stop failure, the script exits without rebooting. API success
means scheduling succeeded, not that every later host action succeeded. Check:

```sh
journalctl -u library-control.service -u library-restart.service -b
systemctl status library-control.socket
```

The API token protects against cross-origin browser requests; it is not a login.
Users who can access the downloader on the Library LAN can restart the appliance.
