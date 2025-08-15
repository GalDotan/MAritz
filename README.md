# **MAritz – FRC WPILOG Replay Over NT**

**MAritz** is a desktop application for replaying `.wpilog` files over NetworkTables in simulation.  
It includes a timeline UI, tray controls, and a minimalist, easy-to-use interface.

![](/DocsMeterial/Demo.gif)

---

## **Features**
- **Open & replay `.wpilog` files** over NetworkTables.
- **Tray icon control** for quick start/stop of log replay.
- **AdvantageScope-style timeline** for easy navigation.
- **Two UI modes**:
  - **Tray Window** – Compact controls and timeline.
  - **Full Window** – Larger timeline view with detailed playback controls.

---

## **Installation**
> **Note:** You must have Python installed before using MAritz.

1. **Download & extract** the provided ZIP file to any folder.  
2. Open the `MAritz` folder.  
3. Run **`MAritz.bat`** to start the program.

---

## **Usage**
1. **Open a log file** – *(GIF example here)*  
2. **Start NT broadcast** – *(GIF example here)*  
3. **Start replaying!** – *(GIF example here)*  

**Note:**  Replay continues even after closing the main window or tray icon, until the process is stopped.

To close the program, right click on the tray icon and press exit.

---

### **Tray Icon Status**
- **Black & White** – No log loaded *(image)*  
- **Red** – Log loaded, replay stopped *(image)*  
- **Green** – Log loaded and replaying *(image)*  

---

## **Robot Code Usage**

MAritz publishes log values over NetworkTables, allowing you to retrieve them in your robot code and use them just like live hardware inputs.

For example:

```java
NetworkTableInstance.getDefault()
    .getTable("/Replay")
    .getEntry("/NT:/MALog/Subsystems/Swerve/Modules/Front Left/Drive Position")
    .getDouble(0);
```

> **Note:**  
> All data is published under the `/Replay` table.  
> Adjust the entry path according to your original logging structure.
