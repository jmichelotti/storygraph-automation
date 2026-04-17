#!/bin/bash
set -e

# Suppress harmless xkbcomp warnings about unresolved keysyms (XF86Camera*, etc.)
# from both Xvfb startup and Chromium connecting to the display later.
export XKB_LOG_LEVEL=0

# Start Xvfb virtual display so headed Playwright works inside the container.
# The code uses headless=False by default and needs a display to attach to.
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp 2>/dev/null &
sleep 0.5

# Optional VNC + noVNC for MFA recovery. Enabled only when ENABLE_VNC=1
# (set by the -mfa compose service variants). When on, open
# http://localhost:6080/vnc.html to drive the browser from your host.
if [ "${ENABLE_VNC:-0}" = "1" ]; then
    x11vnc -display :99 -forever -nopw -shared -bg -rfbport 5900 -quiet
    /usr/share/novnc/utils/novnc_proxy --vnc localhost:5900 --listen 6080 >/dev/null 2>&1 &
    echo "VNC recovery mode: open http://localhost:6080/vnc.html"
fi

exec "$@"
