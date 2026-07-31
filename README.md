# Telit GL865T-DUAL GSM/GPRS modem integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/xestr/home-assistant-sms-modem)
![GitHub activity](https://img.shields.io/github/commit-activity/m/xesutr/home-assistant-sms-modem)

Home Assistant component for Telit GL865 GSM/GPRS modem administration with sensors, list, delete, receive and send SMS. Make call.

Custom Home Assistant integration for **Telit GSM Modules** (e.g., GL865-DUAL, GL865T) connected via Serial USB. 

It allows you to receive SMS messages, store them in a local SQLite database, send individual/bulk SMS, trigger automated phone calls, and manage your inbox directly from your dashboard.

---

## Features

* 📩 **Incoming SMS Processing**: Reads unread messages from SIM card memory and clear them automatically.
* 🧩 **Multipart SMS Support**: Assembles long multi-part SMS messages into a single text.
* 💾 **Persistent SQLite Database**: Saves all received SMS messages into a local SQLite database (`modem.db`) so history is preserved across restarts.
* 📮 **Event Bus Integration**: Fires `telit_gsm_new_sms` events upon incoming SMS for triggering native HA automations.
* 📤 **Send SMS Service**: Support for single or multiple recipient numbers, plus automated fallback to HA helper lists.
* 📞 **Voice Call Service**: Triggers a voice call and automatically hangs up after a set duration.
* 🗑️ **Management Entities**: Includes dynamic `Select` and `Button` entities to remove individual messages from the database.

---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click on the 3 dots in the top right corner and select **Custom repositories**.
3. Add the URL of this repository and set the category to **Integration**.
4. Click **Download**.
5. Restart Home Assistant.

### Method 2: Manual Installation

1. Copy the `custom_components/telit_gsm` directory into your Home Assistant's `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services**.
2. Click **Add Integration** in the bottom right.
3. Search for **Telit GSM** and select it.
4. Fill in the setup parameters:
   * **Serial Port**: e.g., `/dev/ttyUSB0` or `/dev/serial/by-id/...`
   * **Baud Rate**: Default is `115200`
   * **Scan Interval**: Update polling frequency in seconds (Default: `20`)

---

## Services

This integration exposes the following actions/services:

### `telit_gsm.send_sms`
Sends an SMS message to specified target numbers or to the default contact list.

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `target` | String | No | Phone number(s) to send the SMS to (single or comma-separated). If omitted, fallback helper `input_text.sms_bildirim_listesi` is used. |
| `message` | String | **Yes** | The text content of the SMS. |

### `telit_gsm.make_call`
Dials the target phone number and automatically hangs up after the specified duration.

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `target` | String | **Yes** | Target phone number to call (e.g., `05321234567`). |
| `duration` | Integer | No | How many seconds the phone will ring before hanging up (Default: `10`, Range: `3-30`). |

### `telit_gsm.delete_sms`
Deletes an SMS record from the SQLite database and RAM memory.

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `id` | Integer | No | Primary Key ID of the SMS in the database. |
| `sender` | String | No | Sender number (used in pair with timestamp if ID is unknown). |
| `timestamp` | String | No | Timestamp string of the SMS. |

---

## Automations Example

### Trigger on New SMS Arrival

```yaml
alias: "Notify on Incoming SMS"
trigger:
  - platform: event
    event_type: telit_gsm_new_sms
action:
  - service: notify.persistent_notification
    data:
      title: "New SMS from {{ trigger.event.data.sender }}"
      message: "{{ trigger.event.data.content }}"
