#!/usr/bin/env python3

import spidev
import time
import io
import numpy as np

from http.server import BaseHTTPRequestHandler, HTTPServer
from PIL import Image, ImageDraw

W = 256
H = 192
PACKET = 512

OUT_W = 512
OUT_H = 384

spi = spidev.SpiDev()
spi.open(0, 0)
spi.mode = 3
spi.max_speed_hz = 16000000
spi.lsbfirst = False
spi.threewire = False
spi.cshigh = False
spi.no_cs = False

print("Tiny1-C initialized")

# ============================================================
# Thermal palette
# ============================================================

def palette(v):
    if v < 64:
        return 0, 0, int(v * 4)
    elif v < 128:
        return 0, int((v - 64) * 4), 255 - int((v - 64) * 4)
    elif v < 192:
        return int((v - 128) * 4), 255, 0
    else:
        return 255, 255 - int((v - 192) * 4), 0


LUT = np.array(
    [palette(i) for i in range(256)],
    dtype=np.uint8
)


# ============================================================
# Pre-render static color bar
# ============================================================

BAR_X = OUT_W - 27
BAR_Y = 55
BAR_W = 16
BAR_H = 270

bar = Image.new("RGB", (BAR_W, BAR_H))

bar_pixels = bar.load()

for y in range(BAR_H):
    x = 255 - int(y * 255 / (BAR_H - 1))
    color = tuple(int(v) for v in LUT[x])
    for xx in range(BAR_W):
        bar_pixels[xx, y] = color


# ============================================================
# Tiny1-C VoSPI frame
# ============================================================

def get_frame():

    # Ищем начало кадра
    for _ in range(50):

        rx = bytes(
            spi.xfer2([0xAA] + [0] * 511)
        )

        if rx[480] == 1:

            frame_no = (
                rx[482] |
                (rx[483] << 8)
            )

            break

    else:
        return None

    # Получаем 192 строки
    data = bytearray()

    for _ in range(H):

        rx = spi.xfer2(
            [0x55] + [0] * 511
        )

        data.extend(rx)

    # Y16 little-endian.
    # NumPy делает это значительно быстрее Python-цикла.
    vals = np.frombuffer(
        data,
        dtype="<u2"
    ).reshape(H, PACKET // 2)

    # В каждом SPI packet 512 байт.
    # Камерное изображение занимает первые 256 пикселей = 512 байт.
    vals = vals[:, :W]

    return frame_no, vals


# ============================================================
# HTTP MJPEG
# ============================================================

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):

        if self.path != "/thermal":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "multipart/x-mixed-replace; boundary=frame"
        )

        self.send_header(
            "Cache-Control",
            "no-cache"
        )

        self.send_header(
            "Connection",
            "close"
        )

        self.end_headers()

        print("Thermal client:", self.client_address)

        try:

            while True:

                result = get_frame()

                if result is None:
                    continue

                frame_no, vals = result

                # ==================================================
                # Быстрый percentile через NumPy
                # ==================================================

                lo = float(
                    np.percentile(vals, 2)
                )

                hi = float(
                    np.percentile(vals, 98)
                )

                if hi <= lo:

                    lo = float(vals.min())
                    hi = float(vals.max())

                scale = 255.0 / max(
                    1.0,
                    hi - lo
                )

                # ==================================================
                # Быстрое преобразование Y16 -> RGB через LUT
                # ==================================================

                indexes = (
                    (vals.astype(np.float32) - lo) * scale
                ).clip(
                    0,
                    255
                ).astype(
                    np.uint8
                )

                rgb = LUT[indexes]

                img = Image.fromarray(
                    rgb,
                    "RGB"
                )

                # ==================================================
                # 180 градусов
                # ==================================================

                img = img.transpose(
                    Image.Transpose.ROTATE_180
                )

                # ==================================================
                # Увеличение 256x192 -> 512x384
                # ==================================================

                img = img.resize(
                    (OUT_W, OUT_H),
                    Image.Resampling.BILINEAR
                )

                draw = ImageDraw.Draw(img)

                # ==================================================
                # Центральная точка
                # ==================================================

                cx = OUT_W // 2
                cy = OUT_H // 2

                draw.ellipse(
                    (
                        cx - 5,
                        cy - 5,
                        cx + 5,
                        cy + 5
                    ),
                    outline="white",
                    width=2
                )

                # ==================================================
                # Статическая цветовая шкала
                # ==================================================

                img.paste(
                    bar,
                    (BAR_X, BAR_Y)
                )

                draw.text(
                    (OUT_W - 70, 32),
                    "HOT",
                    fill="white"
                )

                draw.text(
                    (OUT_W - 70, BAR_Y + BAR_H + 8),
                    "COLD",
                    fill="white"
                )

                # ==================================================
                # JPEG
                # ==================================================

                buf = io.BytesIO()

                img.save(
                    buf,
                    format="JPEG",
                    quality=75,
                    optimize=False
                )

                jpg = buf.getvalue()

                # ==================================================
                # MJPEG frame
                # ==================================================

                self.wfile.write(
                    b"--frame\r\n"
                )

                self.wfile.write(
                    b"Content-Type: image/jpeg\r\n"
                )

                self.wfile.write(
                    f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                )

                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()

        except (
            BrokenPipeError,
            ConnectionResetError
        ):
            pass

        except Exception as e:
            print("Thermal client error:", e)


# ============================================================
# Server
# ============================================================

print("Thermal HTTP: 8090")
print("Resolution:", W, "x", H)
print("Output:", OUT_W, "x", OUT_H)
print("SPI:", "mode", spi.mode, "20 MHz")

server = HTTPServer(
    ("0.0.0.0", 8090),
    Handler
)

server.serve_forever()
