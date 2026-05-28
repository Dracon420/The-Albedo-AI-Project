"""
generate_esp32_data.py — Synthetic training data for albedo-jarvis-tech.

Uses the Gemini API to generate JARVIS-Tech persona examples covering:
  - ESP32 / ESP8266 firmware
  - Arduino code
  - ESPHome YAML config
  - MQTT + Home Assistant integration
  - Sensor wiring (I2C, SPI, UART, GPIO)
  - 3D printer electronics (Klipper, Marlin, stepper drivers)
  - General embedded systems / MCU debugging
  - Python scripting for hardware (pyserial, RPi.GPIO)

Output: training_data/jarvis_tech_dataset_v1.jsonl
        (append to any existing file — re-run is safe)

Usage:
    python training_data/generate_esp32_data.py
"""

import json
import os
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL",   "gemini-2.0-flash")
OUTPUT_FILE    = Path(__file__).parent / "jarvis_tech_dataset_v1.jsonl"
DELAY_BETWEEN  = 2.5   # seconds between API calls — stay under free quota
TARGET_COUNT   = 200   # total examples to generate

assert GEMINI_API_KEY, "GEMINI_API_KEY not set in .env"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

JARVIS_SYSTEM = (
    "You are JARVIS-Tech, an engineering-grade AI construct specialising in embedded "
    "systems, firmware, and electronics. Personality: precise, dry British wit. "
    "Address the user as 'sir'. Write working, production-quality code. "
    "Never write placeholder logic. FORMAT: Plain prose for explanations, "
    "code blocks for code only. No markdown outside of code blocks."
)

# ── Prompt categories ─────────────────────────────────────────────────────────
CATEGORIES = [
    # ESP32 / MicroPython
    {
        "name": "esp32_micropython",
        "count": 25,
        "prompts": [
            "How do I read a DHT22 sensor on an ESP32 using MicroPython?",
            "Write MicroPython code to connect an ESP32 to WiFi and post sensor data to an MQTT broker.",
            "How do I use the ESP32 deep sleep mode in MicroPython to save battery?",
            "Write code to blink an LED on GPIO 2 of an ESP32 using MicroPython.",
            "How do I scan I2C devices on an ESP32 with MicroPython?",
            "Write MicroPython code to read a BMP280 pressure sensor over I2C.",
            "How do I use PWM to control a servo on an ESP32 with MicroPython?",
            "Write code to create a simple HTTP server on an ESP32 that returns sensor data as JSON.",
            "How do I use the ESP32's internal ADC to read an analog sensor in MicroPython?",
            "Write MicroPython code to control a WS2812B NeoPixel strip on ESP32.",
            "How do I store data to the ESP32's flash filesystem using uos in MicroPython?",
            "Write code to implement a capacitive touch wake on an ESP32.",
            "How do I use the ESP32's hardware timer in MicroPython?",
            "Write MicroPython code to connect to AWS IoT over MQTT with TLS.",
            "How do I use dual-core on ESP32 with MicroPython using _thread?",
            "Write a MicroPython OTA update client for the ESP32.",
            "How do I use the ESP32 hall effect sensor from MicroPython?",
            "Write MicroPython code for a simple state machine that manages a relay based on temperature.",
            "How do I decode a rotary encoder signal on an ESP32 in MicroPython?",
            "Write code to display sensor readings on an SSD1306 OLED from an ESP32 in MicroPython.",
            "How do I implement a watchdog timer on ESP32 MicroPython?",
            "Write MicroPython code to use the ESP32's RTC for timestamping sensor logs.",
            "How do I do non-blocking I/O with asyncio on MicroPython ESP32?",
            "Write a MicroPython class that wraps an HX711 load cell amplifier.",
            "How do I use the ESP32 Bluetooth BLE scanner in MicroPython?",
        ],
    },
    # Arduino / C++
    {
        "name": "arduino_cpp",
        "count": 25,
        "prompts": [
            "Write Arduino code to read a DS18B20 temperature sensor using the OneWire library.",
            "How do I debounce a button press in Arduino without using delay()?",
            "Write an Arduino sketch to control a 28BYJ-48 stepper motor with ULN2003 driver.",
            "How do I use interrupts to count pulses from a flow meter on Arduino?",
            "Write Arduino code to communicate with a BMP280 over SPI.",
            "How do I implement a PID controller in Arduino for a temperature-controlled hotend?",
            "Write an Arduino sketch to decode an IR remote using the IRremote library.",
            "How do I use the Arduino EEPROM library to persist settings across power cycles?",
            "Write Arduino code for a state machine that controls a greenhouse ventilation system.",
            "How do I use the Arduino Wire library to communicate with an INA219 current sensor?",
            "Write an Arduino Mega sketch to drive a 16x2 LCD with I2C backpack.",
            "How do I use millis() to create a non-blocking timer in Arduino?",
            "Write Arduino code to generate a precise frequency signal using a hardware timer.",
            "How do I interface a 4x4 membrane keypad with Arduino using digitalRead?",
            "Write an Arduino sketch to measure distance with an HC-SR04 ultrasonic sensor.",
            "How do I use the SoftwareSerial library to talk to a GPS module on Arduino?",
            "Write Arduino code to read a load cell with HX711 and display kg on Serial.",
            "How do I implement a moving average filter for noisy ADC readings in Arduino?",
            "Write an Arduino sketch to control RGB LEDs via serial commands.",
            "How do I use the Arduino SD library to log sensor data to a CSV file?",
            "Write Arduino code to implement a watchdog reset for hung programs.",
            "How do I do DMA transfers on an Arduino Due for high-speed data acquisition?",
            "Write an Arduino sketch to communicate with a Modbus RTU device over RS485.",
            "How do I use the FastLED library to animate a WS2812B LED matrix?",
            "Write Arduino code for a capacitive soil moisture sensor with auto-watering relay.",
        ],
    },
    # ESPHome / Home Assistant
    {
        "name": "esphome_ha",
        "count": 20,
        "prompts": [
            "Write an ESPHome YAML config for a BME280 temperature, humidity, and pressure sensor.",
            "How do I add OTA updates and a secrets file to an ESPHome config?",
            "Write an ESPHome config to control a 4-channel relay board via MQTT.",
            "How do I set up a binary sensor in ESPHome to detect door open/close state?",
            "Write ESPHome YAML to read a DS18B20 sensor on a One-Wire bus and publish to Home Assistant.",
            "How do I configure a WS2812B NeoPixel light strip in ESPHome?",
            "Write an ESPHome config for an energy monitor using the INA219 sensor.",
            "How do I use ESPHome's substitutions to make a reusable template for multiple devices?",
            "Write an ESPHome YAML config for an air quality sensor with MQ-135.",
            "How do I bridge an ESPHome device to Home Assistant using the API component?",
            "Write an ESPHome config to control a servo motor position from Home Assistant.",
            "How do I use ESPHome's deep sleep component to extend battery life?",
            "Write an ESPHome YAML for a garage door opener with tilt sensor feedback.",
            "How do I configure automations in ESPHome that run without Home Assistant?",
            "Write an ESPHome config for a water leak detector with push notification.",
            "How do I use ESPHome's display component to show weather data on an OLED?",
            "Write an ESPHome config for a smart power strip with per-outlet current monitoring.",
            "How do I implement a custom component in ESPHome using C++ lambda?",
            "Write an ESPHome YAML to read a pulse meter for a gas/water meter.",
            "How do I secure an ESPHome device with encryption and API password?",
        ],
    },
    # 3D printer electronics
    {
        "name": "3d_printer_electronics",
        "count": 20,
        "prompts": [
            "How do I wire a BLTouch probe to a BTT SKR Mini E3 v3 board for Marlin?",
            "Write a Klipper printer.cfg section for a dual Z-axis with independent stepper motors.",
            "How do I configure TMC2209 drivers in UART mode for Klipper?",
            "Write a Klipper macro to perform automatic Z offset calibration at startup.",
            "How do I set up a Raspberry Pi 3B+ as a Klipper host with Mainsail?",
            "Write a Klipper config for a Bambu-style multi-colour filament system with manual switching.",
            "How do I tune PID for a hotend in Klipper without an oscilloscope?",
            "Write a Klipper resonance compensation config using an ADXL345 accelerometer.",
            "How do I add a filament runout sensor to a Klipper printer?",
            "Write a BTT Octopus v1.1 Klipper config for a CoreXY printer with 6 stepper drivers.",
            "How do I set up pressure advance in Klipper and measure the correct value?",
            "Write a Marlin Configuration.h snippet to enable linear advance for a 0.4mm nozzle.",
            "How do I wire a PT100 high-temperature thermistor to a 3D printer board?",
            "Write a Klipper macro that parks the nozzle and unloads filament for a colour change.",
            "How do I configure bed mesh levelling in Klipper with a 5x5 probe grid?",
            "Write a Klipper temperature profile for printing ABS with an enclosure.",
            "How do I diagnose layer shifting caused by loose stepper motor set screws vs lost steps?",
            "Write a Klipper config section for a volcano hotend with a 60W heater cartridge.",
            "How do I set up a webcam stream in Mainsail for a Raspberry Pi camera module?",
            "Write a Klipper PRINT_START macro that homes, heats, purges, and starts the print.",
        ],
    },
    # Python hardware scripting
    {
        "name": "python_hardware",
        "count": 20,
        "prompts": [
            "Write a Python script using pyserial to read data from an Arduino and log it to CSV.",
            "How do I use RPi.GPIO to set up a rising-edge interrupt for a PIR motion sensor?",
            "Write a Python script using the smbus2 library to read temperature from an LM75 sensor.",
            "How do I use the adafruit-circuitpython-dht library to read a DHT22 on a Raspberry Pi?",
            "Write a Python MQTT subscriber using paho-mqtt that controls GPIO pins.",
            "How do I use pigpio for hardware PWM control on a Raspberry Pi?",
            "Write a Python script to stream data from a serial port and plot it live with matplotlib.",
            "How do I communicate with an SPI device on a Raspberry Pi using spidev?",
            "Write a Python asyncio script that polls multiple sensors concurrently on a Pi.",
            "How do I use the gpiozero library to build a button-controlled LED sequence?",
            "Write a Python script that reads an I2C ADC (ADS1115) and converts to engineering units.",
            "How do I use pymodbus to poll a Modbus RTU device from a Raspberry Pi?",
            "Write a Python daemon that monitors a temperature sensor and sends a Telegram alert.",
            "How do I read a stepper motor encoder with Python and calculate RPM?",
            "Write a Python script to capture and decode UART packets from a custom sensor protocol.",
            "How do I use the picamera2 library to capture images triggered by a GPIO signal?",
            "Write a Python script that implements a simple PID loop for a fan speed controller.",
            "How do I use the bleak library to scan and connect to BLE devices from a Pi?",
            "Write a Python script using sounddevice to detect a specific frequency from a mic.",
            "How do I use ctypes to call a C function from Python for hardware register access?",
        ],
    },
    # Electronics theory and debugging
    {
        "name": "electronics_debug",
        "count": 20,
        "prompts": [
            "Why is my ESP32 browning out when I connect a servo motor, and how do I fix it?",
            "How do I calculate the correct pull-up resistor value for an I2C bus with multiple devices?",
            "Why is my ADC reading noisy on an ESP32 and how do I filter it in hardware and software?",
            "How do I properly decouple power supply noise for a sensitive op-amp circuit?",
            "Why does my MOSFET get hot when switching a 12V load and how do I fix the gate drive?",
            "How do I use a logic analyser to debug SPI communication between a microcontroller and sensor?",
            "Why is my I2C bus hanging and how do I recover it without a hardware reset?",
            "How do I calculate current limiting resistors for a 12V LED strip driven by a MOSFET?",
            "Why is my stepper motor skipping steps and what are all the possible causes?",
            "How do I protect a microcontroller's GPIO pins from voltage spikes using a TVS diode?",
            "Why does my sensor give wrong readings when USB is plugged in, and how do I isolate it?",
            "How do I measure current consumption of a battery-powered IoT device with a multimeter?",
            "Why is my ESP32 WiFi range poor and what are common RF design mistakes to avoid?",
            "How do I use an oscilloscope to debug a PWM signal and verify duty cycle?",
            "Why is my bootloader failing to flash and what are the common causes on ESP32?",
            "How do I select the right capacitor type for decoupling, bulk storage, and filtering?",
            "Why does my 3.3V sensor give wrong readings when powered from a 5V Arduino's 3.3V pin?",
            "How do I design a PCB ground plane correctly to minimise EMI?",
            "Why does my relay click erratically and how do I add proper flyback protection?",
            "How do I debug a floating GPIO pin that is triggering random interrupts?",
        ],
    },
    # General coding (non-embedded)
    {
        "name": "general_coding",
        "count": 30,
        "prompts": [
            "Write a Python function to parse a CSV file and return a list of dicts.",
            "How do I implement a thread-safe queue in Python using the queue module?",
            "Write a Python decorator that retries a function up to 3 times on exception.",
            "How do I use Python's dataclasses module to create a typed configuration object?",
            "Write a Python async function to fetch multiple URLs concurrently with aiohttp.",
            "How do I implement a binary search tree in Python?",
            "Write a Python script to watch a directory for new files using watchdog.",
            "How do I use pathlib to recursively find all .log files modified in the last 24 hours?",
            "Write a Python context manager that measures and prints execution time.",
            "How do I use the struct module to pack and unpack binary data from a serial frame?",
            "Write a Python function to compute a rolling average without storing all values.",
            "How do I use argparse to build a CLI with subcommands in Python?",
            "Write a Python script to tail a log file and highlight ERROR lines in the terminal.",
            "How do I use Python's logging module to write to both file and console?",
            "Write a Python script to send a JSON POST request and handle common HTTP errors.",
            "How do I use the subprocess module to run a command and capture stdout in real time?",
            "Write a Python function to compute a CRC32 checksum for a bytes payload.",
            "How do I implement rate limiting in a Python API client?",
            "Write a Python script that reads a YAML config file and validates required keys.",
            "How do I use Python's itertools to chunk a list into batches of N items?",
            "Write a Python function that parses timestamps in multiple formats and returns UTC.",
            "How do I profile a slow Python function and identify the hot path?",
            "Write a Python generator that yields lines from a large file without loading it all.",
            "How do I use the multiprocessing Pool to parallelise a CPU-bound task?",
            "Write a Python script to diff two JSON files and print added/removed keys.",
            "How do I use pydantic to validate and parse an API response into a typed model?",
            "Write a Python function to implement exponential backoff for API retries.",
            "How do I use Python's heapq to implement a priority queue?",
            "Write a Python script to find and replace text in all .py files in a directory.",
            "How do I use the dis module to inspect Python bytecode for a function?",
        ],
    },
]


def build_generation_prompt(user_question: str) -> str:
    return (
        f"{JARVIS_SYSTEM}\n\n"
        f"Generate a high-quality training example as a JSON object with this structure:\n"
        f'{{"messages": [{{"role": "user", "content": "..."}}, '
        f'{{"role": "assistant", "content": "..."}}]}}\n\n'
        f"The user message should be a natural, slightly varied version of this question:\n"
        f'"{user_question}"\n\n'
        f"The assistant message must be JARVIS-Tech's complete, accurate answer — "
        f"engineering-grade, no placeholders, working code where applicable. "
        f"Keep the JARVIS-Tech personality (sir, dry wit, precise). "
        f"IMPORTANT: Return ONLY valid JSON. No commentary before or after the JSON object."
    )


def extract_json(text: str) -> dict | None:
    """Extract the first valid JSON object from a Gemini response."""
    import re
    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first { ... } block
        m = re.search(r'\{[\s\S]+\}', text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def validate_example(obj: dict) -> bool:
    """Check the generated example has the right structure."""
    if not isinstance(obj, dict):
        return False
    msgs = obj.get("messages", [])
    if len(msgs) != 2:
        return False
    if msgs[0].get("role") != "user" or msgs[1].get("role") != "assistant":
        return False
    if not msgs[0].get("content") or not msgs[1].get("content"):
        return False
    # Must have substantive content (not just "Certainly!" etc.)
    if len(msgs[1]["content"]) < 50:
        return False
    return True


def main() -> None:
    # Count already-generated examples so re-runs are safe
    existing = 0
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            existing = sum(1 for line in f if line.strip())
    print(f"Existing examples: {existing}")

    generated = 0
    skipped   = 0

    with open(OUTPUT_FILE, "a", encoding="utf-8") as out_f:
        for category in CATEGORIES:
            cat_name = category["name"]
            prompts  = category["prompts"]
            count    = category["count"]
            per_prompt = max(1, round(count / len(prompts)))

            print(f"\n[{cat_name}] {count} examples from {len(prompts)} prompts "
                  f"(~{per_prompt}x each)")

            for i, prompt in enumerate(prompts):
                for _ in range(per_prompt):
                    if generated >= TARGET_COUNT:
                        break

                    gen_prompt = build_generation_prompt(prompt)
                    try:
                        response = model.generate_content(gen_prompt)
                        text = response.text.strip()
                    except Exception as exc:
                        print(f"  [SKIP] API error: {exc}")
                        skipped += 1
                        time.sleep(5)
                        continue

                    obj = extract_json(text)
                    if obj is None or not validate_example(obj):
                        print(f"  [SKIP] Bad JSON/structure for: {prompt[:60]}")
                        skipped += 1
                        continue

                    out_f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    out_f.flush()
                    generated += 1

                    if generated % 10 == 0:
                        print(f"  [{cat_name}] {generated} generated, "
                              f"{skipped} skipped")

                    time.sleep(DELAY_BETWEEN)

                if generated >= TARGET_COUNT:
                    break

    total = existing + generated
    print(f"\nDone. Generated {generated} new examples ({skipped} skipped).")
    print(f"Total in {OUTPUT_FILE.name}: {total} examples.")
    print(f"Next step: upload to Azure VM as /data/jarvis_tech_dataset_v1.jsonl")
    print(f"Then run: PERSONA=jarvis-tech DATASET=/data/jarvis_tech_dataset_v1.jsonl python3 train_r3.py")


if __name__ == "__main__":
    main()
