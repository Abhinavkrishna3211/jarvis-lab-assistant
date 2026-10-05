// JARVIS: STM32 side. Exposes four calls to the Linux side over the Bridge:
//   point(pan, tilt), laser(on, seconds), box_led(index, colour), ring_state(state)
// The MCU only moves hardware; every decision is made and validated on the Linux side.
#include <Arduino_RouterBridge.h>
#include <Servo.h>
#include <Adafruit_NeoPixel.h>

// Pin map: adjust to your wiring (see docs/wiring.md).
const int PAN_PIN = 5, TILT_PIN = 6, LASER_PIN = 3, STRIP_PIN = 8, RING_PIN = 9;
const int STRIP_LEDS = 8, RING_LEDS = 16;
const unsigned long LASER_MAX_MS = 10000;  // hard safety limit, enforced here as well

Servo pan, tilt;
Adafruit_NeoPixel strip(STRIP_LEDS, STRIP_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel ring(RING_LEDS, RING_PIN, NEO_GRB + NEO_KHZ800);

unsigned long laserOffAt = 0, servoDetachAt = 0, boxOffAt = 0;
String ringMode = "idle";
bool ringDirty = true;

uint32_t colourOf(const String& c, Adafruit_NeoPixel& s) {
  if (c == "red")   return s.Color(255, 0, 0);
  if (c == "amber") return s.Color(255, 140, 0);
  if (c == "blue")  return s.Color(0, 90, 255);
  return s.Color(255, 255, 255);
}

void point(int p, int t) {
  pan.attach(PAN_PIN); tilt.attach(TILT_PIN);
  pan.write(constrain(p, 0, 180)); tilt.write(constrain(t, 0, 180));
  servoDetachAt = millis() + 600;  // detach after the move to stop jitter
}

void laser(bool on, int seconds) {
  if (!on) { digitalWrite(LASER_PIN, LOW); laserOffAt = 0; return; }
  digitalWrite(LASER_PIN, HIGH);
  laserOffAt = millis() + min((unsigned long)seconds * 1000UL, LASER_MAX_MS);
}

void box_led(int index, String colour) {
  strip.clear();
  if (index >= 0 && index < STRIP_LEDS) strip.setPixelColor(index, colourOf(colour, strip));
  strip.show();
  boxOffAt = millis() + 15000;
}

void ring_state(String state) { ringMode = state; ringDirty = true; }

// One solid colour per state, drawn only when the state changes. A redraw every 40 ms (the old
// animation) blocked the Bridge: every call timed out until it was removed. See docs/measurements.md.
void drawRing() {
  if (!ringDirty) return;
  ringDirty = false;
  uint32_t c = ring.Color(0, 10, 40);                                  // idle: dim blue
  if (ringMode == "listening")     c = ring.Color(0, 80, 255);         // bright blue
  else if (ringMode == "thinking") c = ring.Color(140, 75, 0);         // amber
  else if (ringMode == "speaking") c = ring.Color(120, 120, 120);      // white
  else if (ringMode == "error")    c = ring.Color(255, 0, 0);          // red
  ring.fill(c);
  ring.show();
}

void setup() {
  pinMode(LASER_PIN, OUTPUT); digitalWrite(LASER_PIN, LOW);
  strip.begin(); ring.begin(); strip.show(); ring.show();
  Bridge.begin();
  Bridge.provide_safe("point", point);
  Bridge.provide_safe("laser", laser);
  Bridge.provide_safe("box_led", box_led);
  Bridge.provide_safe("ring_state", ring_state);
}

void loop() {
  unsigned long now = millis();
  if (laserOffAt && now >= laserOffAt) { digitalWrite(LASER_PIN, LOW); laserOffAt = 0; }
  if (servoDetachAt && now >= servoDetachAt) { pan.detach(); tilt.detach(); servoDetachAt = 0; }
  if (boxOffAt && now >= boxOffAt) { strip.clear(); strip.show(); boxOffAt = 0; }
  drawRing();
}
