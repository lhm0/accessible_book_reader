# Hardware and GPIO Plan

Last reviewed: `2026-08-18`

Deutsche Fassung: [Hardware- und GPIO-Plan](../docs_DE/HARDWARE_GPIO_PLAN.md)

## Purpose

This document describes the current ABR target hardware and the GPIO
assignment on the `Raspberry Pi 5`.

The controls use a small number of tactile, clearly distinguishable elements:

- `1 x EC11` rotary encoder for volume
- `1 x` push button integrated into the encoder
- `3 x` separate main buttons

## Control Concept

1. `Volume`
   - turn left or right to decrease or increase volume
   - press the encoder for an additional button function
2. `Start / Stop / NFC`
   - starts the NFC query, scan, and audio playback
   - stops an active job or audio playback
3. `Book summary`
   - generates and reads the current book summary
4. `Chapter/latest-pages summary`
   - summarizes the latest relevant section, including open pages

All buttons are wired `active-low` to `GND` and use the Pi's internal pull-ups.
The Start button should be the largest and easiest to locate. The two summary
buttons should be distinguishable by touch.

## Current Hardware

- main computer: `Raspberry Pi 5`
- NFC gateway: `Raspberry Pi Pico`/`RP2040`, connected to the Pi through UART
- NFC readers: `PN5180` or `PN532`, connected exclusively to the Pico
- audio: `MAX98357A` through `I2S`
- controls: `EC11` with push button and three function buttons
- cameras: `2 x Arducam IMX519 16 MP` with 140-degree M12 wide-angle lenses
- camera connection: the two CSI ports on the Pi 5
- lighting: two separately switched LED channels, each driven through a MOSFET

Current hardware sources in the repository:

- Pi main wiring: [hardware/electronics/abr_pi5_header](../hardware/electronics/abr_pi5_header)
- control panel: [hardware/electronics/control_panel](../hardware/electronics/control_panel)
- LED bar: [hardware/electronics/LED_bar_long](../hardware/electronics/LED_bar_long)
- mechanics: [hardware/mechanics](../hardware/mechanics)

`LED_bar_short` is historical and is no longer the active electronics path.

Logical camera assignment:

- left camera on `CAM0`
- right camera on `CAM1`

The cameras use the CSI ports and occupy no GPIOs. The current remaps are
stored at `calibration/out/cam0_planar.npz` and
`calibration/out/cam1_planar.npz`.

## NFC Architecture

There is **no direct communication** between the Raspberry Pi 5 and a
`PN5180` or `PN532` reader. The Pi communicates exclusively with the
Raspberry Pi Pico. The Pico handles reader initialization, protocol access,
tag detection, and status tracking.

The Pi-to-Pico connection is a `115200 8N1` UART using 3.3 V logic levels:

| Raspberry Pi 5 | Physical | Direction | Raspberry Pi Pico | Function |
| --- | --- | --- | --- | --- |
| `BCM14 / TXD` | `8` | Pi → Pico | `GP1 / RX` | commands to the gateway |
| `BCM15 / RXD` | `10` | Pico → Pi | `GP0 / TX` | gateway responses |
| `GND` | any GND pin | shared | `GND` | common reference |

The Pi software uses `/dev/ttyAMA0` by default. The gateway provides a
line-oriented ASCII protocol; the shared client is implemented in
[abr/hardware/pico_gateway_client.py](../abr/hardware/pico_gateway_client.py).

### Current PN5180 Gateway Path

The current preferred path uses up to two PN5180 readers on the Pico's shared
`SPI0` bus. Both readers are active in the current dual-reader firmware, but
are enabled strictly one at a time. They remain in reset while idle.

Pico assignment:

- UART to the Pi: `GP0` = TX, `GP1` = RX
- shared SPI0 bus:
  - `GP16` = MISO
  - `GP18` = SCK
  - `GP19` = MOSI
- PN5180 #1:
  - `GP2` = NSS
  - `GP3` = BUSY
  - `GP4` = RESET
  - `GP5` = IRQ
- PN5180 #2:
  - `GP6` = NSS
  - `GP7` = BUSY
  - `GP8` = RESET
  - `GP9` = IRQ

Firmware and complete wiring details:
[hardware/pn5180_gateway/README.md](../hardware/pn5180_gateway/README.md).

### Alternative PN532 Gateway Path

The alternative Pico path uses two separate I²C buses, allowing both PN532
readers to use the same `0x24` address:

- PN532 #1: `GP4` = SDA, `GP5` = SCL
- PN532 #2: `GP6` = SDA, `GP7` = SCL
- UART to the Pi remains on `GP0/GP1`

In the current default PN532 firmware, reader 1 is active and reader 2 is
prepared but disabled. Details are provided in
[hardware/pn532_gateway/README.md](../hardware/pn532_gateway/README.md).

## Final Raspberry Pi 5 GPIO Assignment

| BCM | Physical | Direction/bus | Function | Notes |
| --- | --- | --- | --- | --- |
| `BCM4` | `7` | Out | `MAX98357A SD_MODE` | optional, planned for the target device |
| `BCM5` | `29` | In | `EC11 A` | encoder channel A |
| `BCM6` | `31` | In | `EC11 B` | encoder channel B |
| `BCM12` | `32` | Out | `LED-left` | MOSFET logic signal, PWM-capable |
| `BCM13` | `33` | Out | `LED-right` | MOSFET logic signal, PWM-capable |
| `BCM14 / TXD` | `8` | UART Out | Pico `GP1 / RX` | Pi sends gateway commands |
| `BCM15 / RXD` | `10` | UART In | Pico `GP0 / TX` | Pi receives gateway responses |
| `BCM16` | `36` | In | `EC11 button` | volume-knob push function |
| `BCM17` | `11` | In | `Start / Stop / NFC` | main button |
| `BCM18` | `12` | I2S BCLK | `MAX98357A BCLK` | dedicated |
| `BCM19` | `35` | I2S LRCLK | `MAX98357A LRC / WS` | dedicated |
| `BCM21` | `40` | I2S DIN | `MAX98357A DIN` | dedicated |
| `BCM22` | `15` | In | `Book summary` | separate button |
| `BCM24` | `18` | In | `Chapter/latest-pages summary` | separate button |

The Pi has no NFC-specific SPI, I²C, `NSS`, `BUSY`, `IRQ`, or `RESET` lines.
In particular, the pins formerly listed for a direct PN5180 path—`BCM7`,
`BCM8`, `BCM9`, `BCM10`, `BCM11`, `BCM23`, and `BCM25`—are no longer reserved
for NFC.

## Reserved and Free Pins

| BCM | Physical | Status | Reason |
| --- | --- | --- | --- |
| `BCM0` | `27` | reserved | EEPROM/HAT special use |
| `BCM1` | `28` | reserved | EEPROM/HAT special use |
| `BCM2` | `3` | keep free | I²C reserve for future Pi extensions |
| `BCM3` | `5` | keep free | I²C reserve for future Pi extensions |
| `BCM7`–`BCM11` | `26, 24, 21, 19, 23` | free | no direct NFC SPI path |
| `BCM14` | `8` | used | UART TXD to the Pico |
| `BCM15` | `10` | used | UART RXD from the Pico |
| `BCM20` | `38` | free | future extension |
| `BCM23` | `16` | free | no direct NFC IRQ |
| `BCM25` | `22` | free | no direct NFC BUSY |
| `BCM26` | `37` | free | future extension |
| `BCM27` | `13` | free | future extension |

## Electrical and Operational Notes

### Pico and NFC

- Pi and Pico require a common ground.
- UART uses 3.3 V logic; do not connect 5 V UART signals.
- `TXD` and `RXD` are crossed: Pi TX to Pico RX, Pico TX to Pi RX.
- Connect PN5180 or PN532 readers only to the Pico as described in the
  corresponding gateway README.
- Switching between the PN5180 and PN532 gateways does not alter Pi wiring.

### Audio and Lighting

- `BCM18`, `BCM19`, and `BCM21` are dedicated to I²S.
- `BCM12` and `BCM13` provide logic signals to the MOSFET drivers only.
- LED loads must not be powered directly from a GPIO.
- [hardware/led_light_test.py](../hardware/led_light_test.py) is available for
  hardware tests.

### Buttons and Encoder

- All four button inputs can be operated `active-low` with internal pull-ups.
- Buttons are debounced in software.
- The production GPIO backend decodes the EC11 using edge interrupts, with a
  polling fallback available.

## Software Implications

The hardware split is represented by the following software components:

- GPIO abstraction for buttons, encoder, and lighting
- one shared UART gateway client for the Pico
- gateway firmware for either PN5180 or PN532
- capture orchestration for NFC query, lighting, cameras, OCR, and TTS
- state logic for start, stop, playback, and summaries

The Raspberry Pi contains no PN5180 or PN532 driver path. Changes to reader
communication belong in the corresponding Pico firmware; the Pi application
remains limited to the UART protocol.

## Summary

The Raspberry Pi 5 directly controls the front panel, lighting, cameras, and
audio. All NFC hardware is encapsulated behind the Raspberry Pi Pico. Apart
from a shared ground, the only connections between Pi and Pico are the UART
lines `BCM14/TXD` and `BCM15/RXD`.
