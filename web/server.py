from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

BASE_DIR = "/opt/pisun-web"
PWM_BASE = "/sys/class/pwm/pwmchip0"
SERVOS = {18: 0, 19: 1}

PERIOD = 20000000
CENTER = 1500000
MIN_US = 1000
MAX_US = 2000

def pwm_path(channel, name):
    return f"{PWM_BASE}/pwm{channel}/{name}"

def write(path, value):
    with open(path, "w") as f:
        f.write(str(value) + "\n")

def setup_servo(gpio):
    channel = SERVOS[gpio]
    directory = f"{PWM_BASE}/pwm{channel}"

    if not os.path.exists(directory):
        write(f"{PWM_BASE}/export", channel)

    write(pwm_path(channel, "enable"), 0)
    write(pwm_path(channel, "period"), PERIOD)
    write(pwm_path(channel, "duty_cycle"), CENTER)
    write(pwm_path(channel, "enable"), 1)

for gpio in SERVOS:
    setup_servo(gpio)

class PiSunHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/api/servo":
            try:
                q = parse_qs(url.query)

                gpio = int(q.get("gpio", ["18"])[0])
                us = int(q.get("us", [str(CENTER)])[0])

                if gpio not in SERVOS:
                    self.send_error(400, "Invalid GPIO")
                    return

                us = max(MIN_US, min(MAX_US, us))
                channel = SERVOS[gpio]

                write(pwm_path(channel, "duty_cycle"), int(us * 1000))

                response = (
                    '{"ok":true,"gpio":%d,"us":%d}'
                    % (gpio, us)
                ).encode()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(response)

            except Exception as e:
                self.send_error(500, str(e))

            return

        super().do_GET()

os.chdir(BASE_DIR)

print("PiSun Web + Hardware PWM Servo server started")

HTTPServer(("0.0.0.0", 8080), PiSunHandler).serve_forever()
