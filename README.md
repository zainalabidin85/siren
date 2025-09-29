# Disaster Warning System with Raspberry Pi 4

This project turns a Raspberry Pi 4 into a **disaster siren system** with:
- **Physical buttons** to start/stop and change modes (Flood / Earthquake / Custom).
- **Web interface (Flask)** to control the siren remotely.
- **PA/Live announcement**: record a short message in your browser and play it immediately.
- **Custom siren upload**: upload your own audio to loop as a siren.
- Raspberry Pi can operate as a **Wi-Fi access point (AP)** for standalone operation.

---

## 🔧 Hardware Requirements
- Raspberry Pi 4 (tested on Raspberry Pi OS Bookworm).
- MicroSD card (>= 16 GB).
- Active speaker(s) connected via 3.5mm audio jack or USB sound card.
- Two push buttons + optional LED:
  - **GPIO17** → Start/Stop button.
  - **GPIO22** → Mode cycle button.
  - **GPIO27** → Status LED (optional).

---

## 📦 Software Requirements
- Raspberry Pi OS (Bookworm recommended).
- Python 3.9+ with Flask.
- ALSA (`aplay`, `amixer`) for audio.
- `ffmpeg` for audio conversion.
- `gpiozero` library for GPIO buttons/LED.

## Install dependencies:
```bash
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg alsa-utils
pip3 install flask gpiozero
```

## ▶️ Running the App:
```
git clone https://github.com/zainalabidin85/siren.git
cd disaster-warning-system
python3 app.py

```

## 🌐 Access Point Mode:
For standalone operation (no router required):
1. Use NetworkManager to configure a hotspot: APsimple
```
sudo nmcli connection add type wifi ifname wlan0 con-name APsimple ssid APsimple \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
  ipv4.method shared
sudo nmcli connection up APsimple
```
2. After reboot, the Pi broadcasts APsimple and Flask is reachable at:
```
https://<raspberry_pi_ip>:5000
```

## 🖥️ Web Features
- Start / Stop siren
- Switch modes: Flood, Earthquake, Custom
- Upload custom WAV
- Record & broadcast annoucements (browser mic required)

How to enable HTTPS on Flask:
1. Create a self-signed certificate on the Pi
```
cd /home/rpi4/warningSystem
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=raspberrypi"
```
2. Run Flask with SSL
```
app.run(host="0.0.0.0", port=5000, threaded=True, ssl_context=("cert.pem", "key.pem"))
```
