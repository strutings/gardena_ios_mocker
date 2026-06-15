# ⚡ Gardena iOS Mocker integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/Version-1.5.5-emerald.svg?style=for-the-badge)
![Maintained](https://img.shields.io/badge/Maintained%3F-Yes-emerald.svg?style=for-the-badge)

An unofficial Home Assistant integration that interfaces directly with Gardena. This integration unlocks advanced controls, synchronous bi-directional cloud status updates, and deep configuration parameters previously exclusive to the official mobile application.

---

## ✨ Features

The integration creates unified, high-fidelity devices in Home Assistant containing the following entities:

* **Robotic Mower Controls & Sensors:**
    * **Central Action Services:** Centrally managed override handlers (`start_override`, `start_automatic`, `park_until_next_task`, and `park_until_further_notice`).
    * **SensorControl:** Multi-step operational selector tracking mower growth sensor algorithms (`Off`, `Low`, `Medium`, `High`).
    * **Deep Config Configuration Numbers:** Direct parameter tuning for *Drive Past Wire* (`cm`) and decimal-range *Remote Start Distance* (`0.2 - 3.0 m`).
    * **Multi-Point Start Matrix:** Dynamic array handlers managing up to 3 individual remote starting point distances (`m`) and proportions (`%`).
    * **Per-Zone Corridor Cut:** Dedicated configuration switches to toggle *Corridor Cut* states individually for each mapped remote start zone/point.
    * **Charging Station Proportion Sensor:** Automatic calculations showing the remainder ratio ($100\% - \text{sum of remote start point proportions}$) starting directly from the charging station base.
* **Irrigation & Valve Smartlets:**
    * **Irrigation Control:** Manual valve duration button with local storage safety wrappers.
    * **Smartlet Weather Protection:** Real-time bi-directional switch state syncing with *Rain Weather Threshold* slider (`1-10 mm`) backed by independent polling threads (`should_poll = True`) to prevent UI bouncing.
    * **Smartlet Soil Moisture Control:** Adaptive tracking for physical soil sensors (`smartlet-sensor`) with native payload mapping for target *Soil Moisture Threshold* sliders (`5-100 %`).

---

## 📸 Preview
Below is a live rendering of the parameters mapped into the Home Assistant interface:

![Gardena iOS Mower Controls Setup](Screenshot%20from%202026-06-11%2018-04-08.png)

---

## 🚀 Installation

### Method 1: Via HACS (Recommended & Direct Shortcut)

The easiest way to install and keep the Gardena iOS Mocker up to date is through HACS. Click the badge below to open the repository setup path directly inside your Home Assistant instance:

[![Open your Home Assistant instance and open a repository in the Home Assistant Community Store.](https://my.homeassistant.io/badgelink/hacs_repository.svg)](https://my.homeassistant.io/redirect/hacs_repository/?owner=strutings&repository=gardena_ios_lo mocker&category=integration)

**Manual HACS Steps:**
1. Open **HACS** from your Home Assistant sidebar.
2. Click the three dots in the upper-right corner and select **Custom repositories**.
3. Paste the repository URL: `https://github.com/strutings/gardena_ios_mocker`
4. Set the Category to **Integration** and click **Add**.
5. Locate "Gardena iOS Mocker" in the list, click **Download**, and restart Home Assistant.

---

### Method 2: Manual Installation

1. Download the latest release asset package from the repository.
2. Extract and copy the `gardena_ios_mocker` folder into your Home Assistant `/config/custom_components/` directory.
3. Restart Home Assistant Core.

---

## 🛠️ Configuration

1. Navigate to **Settings** -> **Devices & Services**.
2. Click **Add Integration** in the bottom right corner.
3. Search for **Gardena iOS Mocker**.
4. Enter your Gardena Cloud account credentials (email and password). The integration will dynamically authorize, fetch your `location_id`, and register device infrastructure platforms from the BFF API streams.

---

## 💎 Advanced Interface Presentation Tip

To map the calculated charging station remainder metric directly as clean secondary undertext/info below your Remote Start Distance slider, you can configure your standard native Dashboard entity row card layout like this:

```yaml
type: entities
entities:
  - entity: number.laila_starting_distance
    name: Remote Start Distance
    secondary_info: charging_station_proportion
