# S-Bahn Departure Display

A CircuitPython app for the [Adafruit MatrixPortal S3](https://www.adafruit.com/product/5778) with a 64×64 RGB LED matrix. Displays real-time Munich S-Bahn departures, local weather, and a playable T-Rex mini-game — all controlled via a built-in web interface.

<img width="812" height="565" alt="image" src="https://github.com/user-attachments/assets/812011fe-a26a-41c0-8e73-f38a2b90a2a0" />

***

## Features

- **S-Bahn Departures** — Real-time departure data from the MVG API; up to 2 upcoming trains with line badges
- **Weather** — Current temperature and weather icon from Open-Meteo
- **T-Rex Game** — Side-scrolling dino game playable from your phone via the web control panel
- **Web Control Panel** — Switch display modes and control the game from any browser on the same network
- **Station Auto-Discovery** — Enter a station name in `settings.toml`; the app resolves it to a station ID automatically via the MVG locations API

<img width="1796" height="621" alt="screenshot" src="https://github.com/user-attachments/assets/ceb414af-9556-4ce8-b20d-5d0e91f8dc02" />

***

## Hardware

| Component | Details |
|-----------|---------|
| Controller | [Adafruit MatrixPortal S3](https://www.adafruit.com/product/5778) (ESP32-S3) |
| Display | 64×64 HUB75 RGB LED Matrix |
| Firmware | CircuitPython 9.x |

***

## Quick Start

**1. Copy files** — Place all `.py` files, `fonts/`, and `images/` onto the CIRCUITPY drive.

**2. Install libraries** — Run `circup` or copy from the [Adafruit Bundle](https://circuitpython.org/libraries):

```
circup install adafruit_bitmap_font adafruit_display_text adafruit_matrixportal adafruit_imageload adafruit_ntp adafruit_requests
```

**3. Configure** — Copy `settings.toml.example` to `settings.toml` and fill in your values:

```toml
CIRCUITPY_WIFI_SSID     = "your-wifi-name"
CIRCUITPY_WIFI_PASSWORD = "your-wifi-password"
SBAHN_STATION_NAME      = "Giesing"   # Any MVG S-Bahn station name
```

**4. Power on** — The MatrixPortal boots, connects to WiFi, resolves your station, and starts displaying departures.

***

## Web Interface

Open a browser to `http://<matrixportal-ip>` to access the control panel:

| Endpoint | Description |
|----------|-------------|
| `/` | Mode switching (S-Bahn Info / T-Rex) |
| `/game` | T-Rex game controller (tap to jump) |
| `/jump` | Jump endpoint (used by the game page) |
| `/restart` | Soft-reboot the device |

***

## Project Structure

```
├── code.py                 # Entry point and main loop
├── settings.py             # Configuration constants (reads settings.toml)
├── wifi_manager.py         # WiFi connect / health-check / reconnect state machine
├── http_client.py          # Non-blocking HTTPS client (cooperative state machine)
├── location_resolver.py    # Station name → globalId + lat/lon (MVG API)
├── sbahn.py                # S-Bahn departure fetcher and parser
├── weather.py              # Weather data fetcher (Open-Meteo)
├── ntp_sync.py             # NTP time sync with DST support
├── web_server.py           # HTTP control server and game controller
├── display_manager.py      # Screen layout, labels, icons, scroll, badges
├── rowscroll.py            # Horizontal text scroll state machine
├── dino_game.py            # T-Rex runner game (64×64 bitmap rendering)
├── button.py               # Debounced GPIO button driver
├── mode_manager.py         # Display mode tracker
├── fonts/                  # BDF pixel font
├── images/                 # Weather icons (BMP) + app icon
└── settings.toml.example
```

***

## Architecture

The app runs on a **cooperative multitasking** model — there is no `time.sleep()` in the main loop. Every module exposes a `tick()` method that does a small piece of work and returns immediately, keeping the display responsive at all times.

Key technical design decisions:

- **Non-blocking HTTP/HTTPS client** — A custom cooperative client implemented as a state machine, handling TCP, TLS, chunked transfer encoding, and header extensions per RFC 7230. Network I/O never stalls the main loop.
- **WiFi state machine** — Connection health is monitored in the background. Reconnection is handled automatically without interrupting the display.
- **Offline mode** — If WiFi is unavailable at startup, the app falls back to offline mode (the clock continues working if NTP was previously synced) and retries the connection in the background.

***

## License

MIT — see [LICENSE](LICENSE) for details.

***
