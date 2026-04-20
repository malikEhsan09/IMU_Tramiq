#!/usr/bin/env bash
set -euo pipefail
cd "/home/tramiq/Desktop/IMU_Tramiq"
if [ -x "/home/tramiq/Desktop/IMU_Tramiq/venv/bin/python" ]; then
    exec "/home/tramiq/Desktop/IMU_Tramiq/venv/bin/python" "/home/tramiq/Desktop/IMU_Tramiq/gui.py"
elif [ -x "/home/tramiq/Desktop/IMU_Tramiq/python/venv/bin/python" ]; then
    exec "/home/tramiq/Desktop/IMU_Tramiq/python/venv/bin/python" "/home/tramiq/Desktop/IMU_Tramiq/gui.py"
else
    exec python3 "/home/tramiq/Desktop/IMU_Tramiq/gui.py"
fi
