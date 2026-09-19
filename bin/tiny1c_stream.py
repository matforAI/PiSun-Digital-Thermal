#!/usr/bin/env python3

import spidev
import time
import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from PIL import Image, ImageDraw, ImageFont

W = 256
H = 192
PACKET = 512

spi = spidev.SpiDev()
spi.open(0, 0)
spi.mode = 3
spi.max_speed_hz = 20000000
spi.lsbfirst = False
spi.threewire = False
spi.cshigh = False
spi.no_cs = False

print("Tiny1-C initialized")

# Iron/thermal palette
def palette(v):
    if v < 64:
        r = 0
        g = 0
        b = int(v * 4)
    elif v < 128:
        r = 0
        g = int((v - 64) * 4)
        b = 255 - int((v - 64) * 4)
    elif v < 192:
        r = int((v - 128) * 4)
        g = 255
        b = 0
    else:
        r = 255
        g = 255 - int((v - 192) * 4)
        b = 0

    return r, g, b

# LUT для скорости
LUT = [palette(i) for i in range(256)]

def percentile(values, p):
    s = sorted(values)
    idx = int((len(s) - 1) * p)
    return s[idx]

def get_frame():

    # Ищем начало кадра
    for _ in range(50):
        rx = bytes(spi.xfer2([0xAA] + [0] * 511))

        if rx[480] == 1:
            frame_no = rx[482] | (rx[483] << 8)
            break
    else:
        return None

    data = bytearray()

    for _ in range(H):
        rx = spi.xfer2([0x55] + [0] * 511)
        data.extend(rx)

    vals = [
        data[i] | (data[i + 1] << 8)
        for i in range(0, len(data), 2)
    ]

    return frame_no, vals


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):

        if self.path == "/thermal":

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame"
            )
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            print("Thermal client:", self.client_address)

            try:
                while True:

                    result = get_frame()

                    if result is None:
                        continue

                    frame_no, vals = result

                    # 2% / 98% вместо голых min/max
                    # убирает одиночные выбросы и горизонтальные вспышки
                    lo = percentile(vals, 0.02)
                    hi = percentile(vals, 0.98)

                    if hi <= lo:
                        lo = min(vals)
                        hi = max(vals)

                    scale = 255.0 / max(1, hi - lo)

                    rgb = bytearray()

                    for v in vals:
                        x = int((v - lo) * scale)

                        if x < 0:
                            x = 0
                        elif x > 255:
                            x = 255

                        r, g, b = LUT[x]
                        rgb.extend((r, g, b))

                    img = Image.frombytes(
                        "RGB",
                        (W, H),
                        bytes(rgb)
                    )

                    # 180 градусов
                    img = img.transpose(Image.Transpose.ROTATE_180)

                    # Увеличение
                    img = img.resize(
                        (768, 576),
                        Image.Resampling.BILINEAR
                    )

                    draw = ImageDraw.Draw(img)

                    # Центральная точка
                    cx = 384
                    cy = 288

                    draw.ellipse(
                        (cx-5, cy-5, cx+5, cy+5),
                        outline="white",
                        width=2
                    )

                    # Текст
                    center = vals[(H // 2) * W + (W // 2)]

                    draw.rectangle(
                        (10, 10, 300, 75),
                        fill=(0, 0, 0)
                    )

                    draw.text(
                        (20, 18),
                        f"FRAME {frame_no}",
                        fill="white"
                    )

                    draw.text(
                        (20, 42),
                        f"Y16 {center}   RANGE {lo}-{hi}",
                        fill="white"
                    )

                    # Цветовая шкала справа
                    bar_x = 735
                    bar_y = 80
                    bar_h = 400
                    bar_w = 20

                    for y in range(bar_h):
                        x = 255 - int(y * 255 / (bar_h - 1))
                        r, g, b = LUT[x]

                        draw.line(
                            (bar_x, bar_y+y,
                             bar_x+bar_w, bar_y+y),
                            fill=(r, g, b),
                            width=1
                        )

                    draw.text(
                        (680, 55),
                        "HOT",
                        fill="white"
                    )

                    draw.text(
                        (680, 485),
                        "COLD",
                        fill="white"
                    )

                    buf = io.BytesIO()

                    img.save(
                        buf,
                        format="JPEG",
                        quality=82
                    )

                    jpg = buf.getvalue()

                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(
                        b"Content-Type: image/jpeg\r\n"
                    )
                    self.wfile.write(
                        f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                    )
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

            except (BrokenPipeError, ConnectionResetError):
                print("Thermal client disconnected")

            return

        # HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PiSun Thermal</title>
<style>
body {
    background:#111;
    color:white;
    font-family:Arial,sans-serif;
    text-align:center;
    margin:20px;
}
h1 {
    font-size:28px;
}
img {
    width:768px;
    max-width:95vw;
    height:auto;
    image-rendering:auto;
}
</style>
</head>
<body>
<h1>Tiny1-C Thermal</h1>
<img src="/thermal">
</body>
</html>
"""

        self.wfile.write(html.encode())


print()
print("===================================")
print(" Tiny1-C COLOR THERMAL")
print(" http://pisun.local:8090/")
print("===================================")
print()

server = HTTPServer(("0.0.0.0", 8090), Handler)
server.serve_forever()
