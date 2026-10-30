#!/bin/sh
set -eu

SOURCE="/workspace/Smart-Route-and-Data-Analyzer/Smart_Route_Analyzer.py"
DEST="/app/project/Smart_Route_Analyzer.py"

if [ ! -f "$SOURCE" ]; then
    echo "ERROR: Smart Route Analyzer source file was not found." >&2
    exit 1
fi

mkdir -p /app/project
cp "$SOURCE" "$DEST"
sed -i "s/self.geometry('1100x700')/self.geometry('1100x900')/" "$DEST"

export DISPLAY=:0


echo "Cleaning up stale display files..."
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0

echo "Starting virtual display..."
Xvfb :0 -screen 0 1280x1000x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

sleep 2

if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "ERROR: Virtual display failed to start."
    cat /tmp/xvfb.log
    exit 1
fi

if [ ! -S /tmp/.X11-unix/X0 ]; then
    echo "ERROR: X11 display socket was not created."
    cat /tmp/xvfb.log
    exit 1
fi


echo "Starting window manager..."
fluxbox >/tmp/fluxbox.log 2>&1 &

echo "Starting local VNC server..."
x11vnc \
    -display :0 \
    -localhost \
    -forever \
    -shared \
    -rfbport 5900 \
    -nopw \
    >/tmp/x11vnc.log 2>&1 &

echo "Starting browser-based GUI gateway..."
websockify \
    --web=/usr/share/novnc \
    6081 127.0.0.1:5900 \
    >/tmp/websockify.log 2>&1 &

sleep 2

echo "Launching Smart Route Analyzer..."
exec python /app/gui_controller.py