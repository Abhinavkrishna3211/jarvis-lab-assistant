# Wiring and calibration

| Part | Connects to | Notes |
|---|---|---|
| Servos (pan, tilt) | STM32 PWM pins D5, D6 | Detached after each move to stop jitter |
| Laser diode | D7 through a logic-level MOSFET | 1 mW or less, firmware off-timer of 10 s |
| WS2812 strip (one LED per box) | D8 | 8 LEDs by default |
| NeoPixel ring (status) | D9 | 16 LEDs |
| Servos, LEDs power | Separate 5 V supply | Shared ground with the UNO Q |
| Mic, speaker | USB sound card on a powered USB-C hub | Hub also feeds the USB camera |

Pins are set at the top of `sketch/sketch.ino`. Servo 1.3.0 and Adafruit NeoPixel 1.15.5 compile on the
`arduino:zephyr` 1.0.0 core (verified 4 Oct 2026; versions pinned in `sketch/sketch.yaml`).

## Calibrating hooks

For each hook, jog the servos until the laser dot sits on it, then store the pan and tilt angles in the
`locations` table. Record the miss distance in centimetres for the evaluation.
