# Possible future allowlisted client tools

The backend must not implement these local-OS actions. If reconsidered, design
and review each as a narrowly scoped, allowlisted Electron client tool with
explicit permission, validation, and tests. Never add arbitrary command execution.

- Shell execution or arbitrary command paths: do not restore; consider only
  concrete, individually allowlisted client actions.
- Keyboard and mouse automation, text typing, and clipboard read/write.
- Local process listing/termination, window tracking, and active-window details.
- Host CPU, RAM, disk, network, battery, and power-state monitoring or alerts.
- Local file search/read/write and folder creation.
- Local screenshot capture, screen analysis, and continuous camera streams,
  motion detection, or camera management routes. Keep camera capture opt-in and
  on-demand through the paired client only.
- Local volume and media controls, shutdown, restart, sleep, hibernate, and
  other direct OS power actions.
- Local MQTT broker control. Smart-home integrations must use provider cloud APIs.
