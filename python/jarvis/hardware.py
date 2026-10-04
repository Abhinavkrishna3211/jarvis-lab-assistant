"""STM32 side of the Bridge. Same four calls the Arduino sketch exposes:
point(pan, tilt), laser(on, seconds), box_led(index, colour), ring_state(state)."""


class SimHardware:
    """Records calls so everything runs and tests off-board."""

    def __init__(self, verbose=False):
        self.calls, self.verbose = [], verbose

    def _rec(self, *c):
        self.calls.append(c)
        if self.verbose:
            print("[hw]", *c)

    def point(self, pan, tilt): self._rec("point", pan, tilt)
    def laser(self, on, seconds=10): self._rec("laser", on, min(seconds, 10))
    def box_led(self, index, colour="white"): self._rec("box_led", index, colour)
    def ring_state(self, state): self._rec("ring_state", state)


class BridgeHardware:
    """Real UNO Q: Linux (MPU) -> STM32 (MCU) through Arduino App Lab's Bridge (MessagePack RPC).
    Angles are sent as ints and colours as names so the sketch's handlers stay trivial."""

    def __init__(self):
        from arduino.app_utils import Bridge  # only exists inside App Lab
        self.call = Bridge.call

    def point(self, pan, tilt): self.call("point", int(pan), int(tilt))
    def laser(self, on, seconds=10): self.call("laser", bool(on), int(min(seconds, 10)))
    def box_led(self, index, colour="white"): self.call("box_led", int(index), str(colour))
    def ring_state(self, state): self.call("ring_state", str(state))
