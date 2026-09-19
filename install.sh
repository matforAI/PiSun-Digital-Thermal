#!/bin/bash
set -e

echo
echo "=============================================="
echo " PiSun-Digital-Thermal installer"
echo " Raspberry Pi Zero 2 W / Debian"
echo "=============================================="
echo

if [ "$EUID" -ne 0 ]; then
    echo "Запусти установщик через sudo:"
    echo "sudo bash install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------
# Определяем пользователя Raspberry Pi
# ------------------------------------------------

if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    INSTALL_USER="$SUDO_USER"
else
    INSTALL_USER="$(getent passwd 1000 | cut -d: -f1)"
fi

if [ -z "$INSTALL_USER" ]; then
    echo "ОШИБКА: не удалось определить пользователя Raspberry Pi."
    exit 1
fi

INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"

echo "[1/10] Пользователь: $INSTALL_USER"
echo "[1/10] HOME: $INSTALL_HOME"

# ------------------------------------------------
# Пакеты
# ------------------------------------------------

echo
echo "[2/10] Устанавливаю зависимости..."

apt-get update

apt-get install -y \
    git \
    curl \
    ca-certificates \
    tar \
    i2c-tools \
    python3 \
    python3-spidev \
    python3-smbus \
    python3-pil \
    python3-numpy \
    python3-venv \
    python3-pip-whl

# ------------------------------------------------
# I2C / SPI / PWM
# ------------------------------------------------

echo
echo "[3/10] Настраиваю I2C / SPI / PWM..."

CONFIG="/boot/firmware/config.txt"

# Удаляем старый конфликтующий nospi10
sed -i '/^[[:space:]]*dtoverlay=nospi10[[:space:]]*$/d' "$CONFIG"

grep -q '^dtparam=i2c_arm=on' "$CONFIG" || \
    echo 'dtparam=i2c_arm=on' >> "$CONFIG"

grep -q '^dtparam=spi=on' "$CONFIG" || \
    echo 'dtparam=spi=on' >> "$CONFIG"

grep -q '^dtoverlay=pwm-2chan' "$CONFIG" || \
    echo 'dtoverlay=pwm-2chan' >> "$CONFIG"

mkdir -p /etc/modules-load.d

cat > /etc/modules-load.d/i2c-dev.conf <<EOF
i2c-dev
EOF

modprobe i2c-dev || true

# ------------------------------------------------
# Создаём каталоги
# ------------------------------------------------

echo
echo "[4/10] Устанавливаю файлы проекта..."

mkdir -p /usr/local/bin
mkdir -p /opt/pisun-web
mkdir -p /etc/mediamtx

cp "$SCRIPT_DIR/bin/tiny1c-start.sh" /usr/local/bin/tiny1c-start.sh
cp "$SCRIPT_DIR/bin/tiny1c_stream.py" /usr/local/bin/tiny1c_stream.py

cp "$SCRIPT_DIR/web/server.py" /opt/pisun-web/server.py
cp "$SCRIPT_DIR/web/index.html" /opt/pisun-web/index.html

cp "$SCRIPT_DIR/config/mediamtx.yml" /etc/mediamtx/mediamtx.yml

chmod +x /usr/local/bin/tiny1c-start.sh
chmod +x /usr/local/bin/tiny1c_stream.py

chown -R "$INSTALL_USER:$INSTALL_USER" /opt/pisun-web

# ------------------------------------------------
# Подставляем пользователя в Tiny1-C
# ------------------------------------------------

sed -i "s/runuser -u pipi/runuser -u $INSTALL_USER/g" \
    /usr/local/bin/tiny1c-start.sh

# ------------------------------------------------
# MediaMTX
# ------------------------------------------------

echo
echo "[5/10] Устанавливаю MediaMTX..."

MEDIAMTX_VERSION=""

if [ -f "$SCRIPT_DIR/MEDIAMTX_VERSION.txt" ]; then
    MEDIAMTX_VERSION="$(grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' \
        "$SCRIPT_DIR/MEDIAMTX_VERSION.txt" | head -n1 || true)"
fi

# Если версия не определилась — берём актуальный релиз
if [ -z "$MEDIAMTX_VERSION" ]; then
    echo "Версия MediaMTX не определена, получаю latest..."
    MEDIAMTX_VERSION="$(curl -fsSL \
        https://api.github.com/repos/bluenviron/mediamtx/releases/latest |
        python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')"
fi

echo "MediaMTX: $MEDIAMTX_VERSION"

ARCH="$(dpkg --print-architecture)"

case "$ARCH" in
    arm64)
        MTX_ASSET="mediamtx_${MEDIAMTX_VERSION#v}_linux_arm64.tar.gz"
        ;;
    armhf)
        MTX_ASSET="mediamtx_${MEDIAMTX_VERSION#v}_linux_armv7.tar.gz"
        ;;
    amd64)
        MTX_ASSET="mediamtx_${MEDIAMTX_VERSION#v}_linux_amd64.tar.gz"
        ;;
    *)
        echo "ОШИБКА: неподдерживаемая архитектура: $ARCH"
        exit 1
        ;;
esac

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

MTX_URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/${MTX_ASSET}"

echo "Скачиваю:"
echo "$MTX_URL"

curl -fL "$MTX_URL" -o "$TMPDIR/mediamtx.tar.gz"

tar -xzf "$TMPDIR/mediamtx.tar.gz" -C "$TMPDIR"

install -m 0755 "$TMPDIR/mediamtx" /usr/local/bin/mediamtx

# ------------------------------------------------
# systemd
# ------------------------------------------------

echo
echo "[6/10] Устанавливаю systemd-сервисы..."

cp "$SCRIPT_DIR/systemd/mediamtx.service" \
    /etc/systemd/system/mediamtx.service

cp "$SCRIPT_DIR/systemd/tiny1c.service" \
    /etc/systemd/system/tiny1c.service

cp "$SCRIPT_DIR/systemd/pisun-web.service" \
    /etc/systemd/system/pisun-web.service

# Подставляем реального пользователя
sed -i "s/User=pipi/User=$INSTALL_USER/g" \
    /etc/systemd/system/pisun-web.service

# Tiny1-C service запускает start.sh от root,
# поэтому там отдельная подстановка уже сделана выше.

systemctl daemon-reload

# ------------------------------------------------
# Включаем автозапуск
# ------------------------------------------------

echo
echo "[7/10] Включаю автозапуск..."

systemctl enable mediamtx.service
systemctl enable tiny1c.service
systemctl enable pisun-web.service

# ------------------------------------------------
# Git
# ------------------------------------------------

echo
echo "[8/10] Проверяю Git..."

git --version

# ------------------------------------------------
# Проверка файлов
# ------------------------------------------------

echo
echo "[9/10] Проверяю установленные файлы..."

test -x /usr/local/bin/mediamtx
test -x /usr/local/bin/tiny1c-start.sh
test -f /usr/local/bin/tiny1c_stream.py
test -f /opt/pisun-web/server.py
test -f /opt/pisun-web/index.html
test -f /etc/mediamtx/mediamtx.yml

echo "Файлы OK."

# ------------------------------------------------
# Запуск
# ------------------------------------------------

echo
echo "[10/10] Запускаю сервисы..."

systemctl restart mediamtx.service || true
systemctl restart pisun-web.service || true
systemctl restart tiny1c.service || true

echo
echo "=============================================="
echo " Установка завершена"
echo "=============================================="
echo
echo "После перезагрузки автоматически запустятся:"
echo "  MediaMTX"
echo "  Tiny1-C"
echo "  PiSun Web"
echo
echo "PiSun Web:  http://<hostname>.local:8080/"
echo "Thermal:    http://<hostname>.local:8090/thermal"
echo "Camera:     http://<hostname>.local:8889/cam/"
echo
echo "ВАЖНО: после изменения config.txt нужна перезагрузка."
echo
read -r -p "Перезагрузить Raspberry Pi сейчас? [Y/n]: " ANSWER
ANSWER="${ANSWER:-Y}"

if [[ "$ANSWER" =~ ^[YyДд]$ ]]; then
    echo "Перезагрузка через 3 секунды..."
    sleep 3
    reboot
fi
