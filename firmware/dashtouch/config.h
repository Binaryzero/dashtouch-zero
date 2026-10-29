#pragma once
// Hardware configuration. Everything here is safe to commit.

// --- Sensor UART pins ------------------------------------------------
// ESP32-S3-Zero: TX pad is GPIO43; RX pad is GPIO44.
// Sensor RX (brown) connects to board TX.
// Sensor TX (yellow) connects to board RX.
//
// GPIO43/44 are also the chip's UART0 console pins, so the brown lead
// sees a short burst of ROM boot-log bytes (115200 baud) at every
// reset. The sensor ignores anything that isn't a valid 0xEF01 packet,
// so this is harmless. FingerSerial is UART1, routed to these pads
// through the GPIO matrix.
//
// Don't edit these to swap orientation: `dashtouch pins --swap` stores
// fp_swap on the device and reverses the two values at boot. A board
// that was swapped before a reflash keeps that setting — if it comes up
// silent, run `dashtouch pins --normal` and power-cycle.
#define DT_FP_TX_PIN 43
#define DT_FP_RX_PIN 44

#define DT_UART_BAUD 57600

// --- Behavior --------------------------------------------------------
#define DT_POLL_MS 150          // GenImg poll cadence while idle
#define DT_RESULT_HOLD_MS 1200  // how long match/no-match colors linger
#define DT_PRESS_ENTER 1        // factory default only — the NVS-stored
                                 // press_enter setting wins once set (see
                                 // settings.cpp)

// --- Finger detection ------------------------------------------------
// Default: poll the sensor itself (works on every module, no extra
// wiring assumptions). Optional: gate polling on the WAKEUP line (blue
// lead on the pad labeled GP8) — set DT_USE_WAKEUP_PIN 1 and pick the
// polarity your module actually idles at. One known module idles at the
// "active" level, which makes the pin useless — polling is the safe
// default, so the blue lead never gates sensor polling unless you opt
// in here.
#define DT_USE_WAKEUP_PIN 0
#define DT_WAKEUP_PIN 8         // pad labeled GP8 (GPIO8)
#define DT_WAKEUP_ACTIVE LOW    // level meaning "finger present"

#define DT_MIN_SLOT 1
#define DT_MAX_SLOT 200

// Project version, compiled in. One repo, one version — this must match
// helper/dashtouch_helper/__init__.py's __version__ (and version.json,
// which stays in sync with it). Update all three together.
#define DT_FW_VERSION "0.1.0"
