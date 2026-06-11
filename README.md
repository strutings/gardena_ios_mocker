# ⚡ Gardena iOS Mocker integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/Version-1.5.0-emerald.svg?style=for-the-badge)
![Maintained](https://img.shields.io/badge/Maintained%3F-Yes-emerald.svg?style=for-the-badge)

An unofficial Home Assistant integration that interfaces directly with Gardena. This integration unlocks advanced controls, synchronous bi-directional cloud status updates, and deep configuration parameters previously exclusive to the official mobile application.
---

## ✨ Features

The integration creates unified, high-fidelity devices in Home Assistant containing the following entities:

* **Robotic Mower Controls & Sensors:**
    * **Central Action Services:** Centrally managed override handlers (`start_override`, `start_automatic`, `park_until_next_task`, and `park_until_further_notice`).
    * **SensorControl:** Multi-step operational selector tracking mower growth sensor algorithms (`Off`, `Low`, `Medium`, `High`).
    * **Deep Config Configuration Numbers:** Direct parameter tuning for *Drive Past Wire* (`cm`) and *Remote Start Distance* (`m`).
    * **Multi-Point Start Matrix:** Dynamic array handlers managing up to 3 individual remote starting point distances (`m`) and proportions (`%`).
* **Irrigation & Valve Smartlets:**
    * **Irrigation Control:** Manual valve duration button with local storage safety wrappers.
    * **Smartlet Weather Protection:** Real-time bi-directional switch state syncing with *Rain Weather Threshold* slider (`1-10 mm`) backed by independent polling threads (`should_poll = True`) to prevent UI bouncing.
    * **Smartlet Soil Moisture Control:** Adaptive tracking for physical soil sensors (`smartlet-sensor`) with native payload mapping for target *Soil Moisture Threshold* sliders (`5-100 %`).

---
