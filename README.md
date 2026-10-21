# muscle-fatigue

Local EMG analysis prototype for measuring relative muscle activity from an ESP32-based setup.

This project is a lightweight tool for collecting, analyzing, and visualizing surface EMG (sEMG) data from an ESP32-C6 Zero over Wi‑Fi. It includes a local Python backend, a browser-based frontend, signal-processing logic, and support for saving and reviewing analyses.

The project is intended for experimentation and further development. It is not a validated clinical or medical fatigue classifier.

## Overview

The application lets a user:

- connect to an ESP32 device over Wi‑Fi
- record EMG data in real time
- calculate RMS and MAV values
- create an automatic reference from rest and activity
- display a relative amplitude indicator in the browser
- save analyses locally
- reopen previous measurements
- import text files for offline analysis
- run a simulated demo without hardware

## Features

- Live EMG recording from ESP32 via TCP
- Real-time signal plotting in the browser
- Relative amplitude index based on rest/activity calibration
- Built-in demo mode for testing without hardware
- Local JSON-based result storage
- CSV export of RMS and MAV values
- Manual inspection and editing of saved analyses
- Basic file import analysis workflow
- Unit tests for backend and UI behavior

## Project structure

```text
muscle-fatigue/
├── README.md
├── kretsschema.png
├── FinalPresentation (1) (1).pdf
├── Kalkylkod/
│   ├── README.md
│   ├── server.py
│   ├── emg_core.py
│   ├── amplitude_index.py
│   ├── index.html
│   ├── requirements.txt
│   ├── simulate_esp32.py
│   ├── test_web.py
│   ├── test_ui.cjs
│   └── esp32_emg/
│       └── esp32_emg.ino
```

## Stack

- Python
- HTML/CSS/JavaScript
- C++ (Arduino firmware for ESP32)
- NumPy for signal processing

## How it works

The workflow is:

1. The ESP32 reads the EMG signal from the configured ADC input.
2. Data is sent to the local Python server over Wi‑Fi/TCP.
3. The server normalizes and filters the signal.
4. RMS and MAV are computed over sliding windows.
5. A rest phase is used to estimate baseline activity.
6. An active phase creates an automatic reference.
7. The browser shows the relative amplitude score and status.
8. The user can save the result locally for later review.

This implementation is designed as a prototype and engineering tool, not as a clinically validated fatigue measurement system.

## Getting started

### Requirements

- Python 3
- NumPy
- Optional: Node.js for UI tests
- ESP32 hardware
- Circuit board
- 1x INA128
- 2x LF365N
- Resistors: 2.0k, 100k, 390K, 2x 10k, 100 (Ohm)
- Capacitors: 82n, 910p, 1µ (F)
- 1x L785S05CV (Regulator)
- 2x 9V battery
- 2x Diode
- 3x EKG or surfare EMG electrodes
- Wires

### Build the Circuit

Build the circuit shown in the 'schematic_sEMG.webp' file. 
Troubleshoot the circuit as you build it to make sure that everything works.

### Install dependencies

* Download the all the files from the 'Kalkylkod' folder.

* Open the folder in VSCode.

* Open a new terminal and enter the following command separately: 

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Run the app

```bash
python3 server.py
```

Then open:

```text
http://127.0.0.1:8000
```

### ESP32 setup

* Intall ArduinoIDE from the web.

* Copy the code from the file 'esp32_emg.io' under the 'Kalkylkod' folder and paste it in a new sketch.

* In ArduinoIDE download 'esp32 by Espressif Systems' under the board manager tab and choose 3.3.5 or later  version.

* Select Tools -> Board -> esp32 -> 'Waveshare ESP32' with the name of your specific ESP32 model (e.g Waveshare ESP32-C6-Zero)

* Press verify and upload the code on to the ESP32

### Operation 

* Place the two measurement electrodes close together over the muscle you want to measure. Position the third electrode separately to serve as a reference.

* While running the program from VSCode go to WiFi setting on your computer and select "ESP32-EMG
" and enter the standard password "emgsetup2026" (alternatively you can choose your own password in the 'esp32_emg.ino' file on this line of code:)

```bash
const char *AP_PaSSWORD = "emgsetup2026"
```

* Press record on the program and follow the instructions given.

* When the set recording time ends, or you stop the recording manually, the program will ask whether you want to save or discard it.

* View your saved recordings under the “Mina analyser” tab.


## Demo mode

The project includes a simulated signal mode that runs without a physical ESP32. This is useful for validating the system flow, calibration logic, and recording behavior in a controlled environment.

## Testing

### Python tests

```bash
cd Kalkylkod
python3 -m unittest -v test_web.py
```

### UI tests

```bash
cd Kalkylkod
node test_ui.cjs
```

## Important limitation

This project does not measure "muscle fatigue" in a medical or validated sense. What it measures is a relative change in signal amplitude compared to a local reference. That makes it useful for prototype testing and exploration, but it should not be interpreted as a scientific fatigue classification without further validation.

## Further development

There is a clear path for extending the project:

- separate backend and frontend responsibilities more cleanly
- improve data persistence and metadata handling
- add more EMG metrics beyond RMS/MAV
- improve the UI and user workflow
- test deeper on real hardware and real recordings
- make the signal analysis more modular and robust

## Notes

The repository includes supporting technical documentation in `Kalkylkod/README.md`, as well as circuit information in `kretsschema.png`. The presentation file in the repo root likely provides additional project context and final presentation material.

---

This project is best understood as a local EMG research prototype for monitoring relative muscle activity and experimenting with automated reference generation in a practical setup.
