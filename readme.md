# FRC Log Replayer

A Windows tray-style application for **offline replay** of FRC (FIRST Robotics Competition) WPILOG files.  
Convert, visualize, scrub, and broadcast robot-runtime data in **real-time** to NetworkTables.

---

## 🚀 Features

- **WPILOG → CSV** converter (runs off the UI thread)
- **Scrubbable, zoomable timeline** with:
  - Colored segments (gray = disabled, green = autonomous, blue = teleop, red = e-stop)
  - Auto-scrolling cursor, fixed thickness
  - Click to seek, two-finger scroll to pan, mouse-wheel to zoom
  - Dynamic tick marks & second labels
- **Tray icon** with a compact bottom-right control panel:
  - Open Log
  - Play / Stop Replay
  - Start / Stop NetworkTables broadcast
  - Open Full App window
  - Close (`✕`) without exiting the tray
- **Full window** mode for advanced control and live status/progress display
- **Type-correct publishing** to NT (booleans, numbers, arrays, strings)

---

## 🎯 Goal

Provide FRC teams with an **easy, stand-alone** tool to replay robot logs exactly as they happened, inspect match data, and feed it back into tools/dashboard via NetworkTables—**no live robot required**.

---

## ⚙️ How It Works

1. **Parse** WPILOG binary using a custom `DataLogReader`.
2. **Convert** all entries to a temporary CSV (timestamps in seconds).
3. **Load & sort** CSV into memory (skipping any timestamp > 1000 s).
4. **Compute** DS state intervals from log entries `DS:enabled`, `DS:autonomous`, `DS:estop`.
5. **Render** colored segments & cursor on a Qt QGraphicsView timeline.
6. **Replay** by stepping through sorted entries in real time (based on `time.perf_counter()`).
7. **Optionally** publish each entry back to NetworkTables with correct type.

---

## 📦 Requirements

- **Windows 10/11**
- **Python 3.10+** (tested on 3.13)
- **Pip**  
- **PySide6**, **ntcore** (optional if you skip NT publish), **PyInstaller** (for packaging)

---

## 🛠️ Development Setup

```bash
git clone <your-repo-url>
cd FRCLogReplay

# 1) Create & activate venv
python -m venv venv
venv\Scripts\activate

# 2) Install deps
pip install --upgrade pip
pip install PySide6 ntcore
```

Run the app:
```
python main.py
``` 

---

🏗️ Build Standalone EXE
We use PyInstaller to bundle everything into one `.exe`:

```
# from project root (where main.py and icon.ico live)
pip install pyinstaller

pyinstaller --onefile --windowed --icon=icon.ico --add-data "icon.ico;." main.py
```

- `--onefile` → single `main.exe` in `dist/`
- `--windowed` → GUI mode (no console)
- `--icon=icon.ico` → set your tray & taskbar icon
- `--add-data "icon.ico;."` → bundle the icon so `QIcon(str(icon_path))` still works

After it finishes, distribute only `dist\main.exe`.

---

⚖️ License
This project is provided as-is.
Feel free to adapt for your team’s needs!