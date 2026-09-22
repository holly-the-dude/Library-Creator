# update_display role

This role sends a status message to an existing Library display HTTP service.
It does not install the display service or configure a TFT/HDMI screen. Current
runtime startup also uses the host's `displayit` helper for splash images; see the
[developer guide](../../../docs/DEVELOPERS.md#display-abstraction).

## Requirements and behavior

Ansible must be able to reach `http://<dhost>:6901/upload-text`. The role POSTs a
raw `html_data` body containing **Hotspot Started**, colored yellow with a white
border, then prints the registered response with `debug`. The request task uses
`become: true`.

The task accepts response status `200`, `500` and `-1`; task success alone is not
proof that the display updated. Inspect the registered response when diagnosing
connection or server errors.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `dhost` | `library` | Hostname/IP of the display service |

Message text, color and border are currently task-local variables in
[`tasks/main.yml`](tasks/main.yml). Edit that task to change them; they are not
exposed as configurable role defaults. No role dependencies are declared.

## Example

From a playbook under `setup_library/`:

```yaml
- hosts: localhost
  connection: local
  roles:
    - role: update_display
      dhost: 127.0.0.1
```

The receiver must already be running. For the deployed startup flow, see
[`start_library.yml`](../../files/start_library.yml).
