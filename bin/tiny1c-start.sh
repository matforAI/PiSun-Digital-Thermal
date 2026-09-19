#!/bin/bash
set -e

echo "[Tiny1-C] Loading I2C..."
modprobe i2c-dev

# Ждём появления I2C-1
for i in $(seq 1 20); do
    if [ -e /dev/i2c-1 ]; then
        break
    fi
    sleep 0.5
done

if [ ! -e /dev/i2c-1 ]; then
    echo "[Tiny1-C] ERROR: /dev/i2c-1 not found"
    exit 1
fi

echo "[Tiny1-C] Waiting for camera..."

# Ждём появления камеры на 0x3c
for i in $(seq 1 20); do
    if i2cdetect -y 1 2>/dev/null | grep -q "3c"; then
        break
    fi
    sleep 0.5
done

echo "[Tiny1-C] Camera detected"

# ----------------------------------------
# PREVIEW STOP
# ----------------------------------------
echo "[Tiny1-C] Preview STOP"

i2ctransfer -y 1 \
    w10@0x3c \
    0x1d 0x00 \
    0x0f 0x02 0x00 0x00 0x00 0x00 0x08 0x00

sleep 0.2

# ----------------------------------------
# PREVIEW START
# 256x192 / 25 FPS / VOSPI
# ----------------------------------------
echo "[Tiny1-C] Preview START"

i2ctransfer -y 1 \
    w18@0x3c \
    0x1d 0x00 \
    0x0f 0xc1 0x00 0x00 0x00 0x00 0x08 0x00 \
    0x00 0x00 0x01 0x00 0x00 0xc0 0x19 0x08

sleep 0.3

# ----------------------------------------
# Y16 GAMMA
# ----------------------------------------
echo "[Tiny1-C] Y16 GAMMA"

i2ctransfer -y 1 \
    w10@0x3c \
    0x1d 0x00 \
    0x0a 0x01 0x00 0x00 0x00 0x09 0x00 0x00

sleep 0.5

# ----------------------------------------
# SHUTTER STATUS
# ----------------------------------------
echo "[Tiny1-C] Shutter status"

i2ctransfer -y 1 \
    w10@0x3c \
    0x1d 0x00 \
    0x0c 0x83 0x00 0x00 0x00 0x00 0x00 0x02

i2ctransfer -y 1 \
    w2@0x3c \
    0x1d 0x08

i2ctransfer -y 1 \
    r2@0x3c || true

echo "[Tiny1-C] Initialization complete"

# Запускаем сам thermal stream от пользователя pipi
exec runuser -u pipi -- /usr/bin/python3 /usr/local/bin/tiny1c_stream.py
