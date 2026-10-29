# When it doesn't work

Every fix in here was earned the hard way on the very first build. Work
top to bottom — the list is ordered by "most likely culprit."

## The ring never turns purple

The firmware can't talk to the sensor. In order:

1. **Count your wires. All six?** The white one (touch power) is the
   classic miss — without it the sensor *receives* commands and even
   executes them, but physically cannot answer. Every symptom looks like
   a dead sensor. It isn't. Both red and white go to `3V3`.
2. **Yellow and brown swapped?** Yellow (sensor's voice) goes to `RX`
   (GPIO44), brown (sensor's ears) goes to `TX` (GPIO43) — the top two
   pads on the right edge of the ESP32-S3-Zero with the USB-C at the
   top. Crossed pairs are silent.
3. **Loose leads.** If you're using clip leads or a breadboard, tug-test
   each one. A clip that looks attached but isn't can cost you a
   full evening.
4. **A stale swap setting.** `dashtouch pins --swap` stores its choice on
   the board itself, and that setting survives a reflash. A board that
   was ever swapped comes back up with GPIO43 and GPIO44 reversed, so a
   firmware update alone won't un-cross them: with the helper running,
   run `.venv/bin/dashtouch pins --normal`, then power-cycle the board
   (unplug and replug the USB cable). `.venv/bin/dashtouch pins` with no
   flag shows the current orientation.
5. **Rare, but real: the board itself.** The original build's QT Py could
   not transmit on its `TX` pad at all. [firmware/diagnostics/](../firmware/diagnostics/README.md)
   has `fp_loopback`, which settles it in two minutes with a single jumper
   wire (sensor unplugged) — if it shows zeros flooding in one direction,
   run `.venv/bin/dashtouch pins --swap`. It moves the sensor UART to the
   other pin pair without a reflash — it stores the choice on the board
   and asks for a power-cycle — and the ring tells you whether the sensor
   came back. Only the sensor wiring is affected — the USB link to your
   Mac never changes — so it's always safe to try.

## The board seems completely dead

- **Is your cable a charging cable?** Plenty of USB-C cables carry no
  data. Try the cable you use for a hard drive or a camera — or grab
  [a data-capable one](https://amzn.to/4zjg9p9) if you're not sure yours
  qualifies.
- **Serial silence isn't death.** The board only speaks when the Mac
  asserts a control signal called DTR. Our tools do this automatically;
  random serial apps may not. Trust `.venv/bin/dashtouch doctor` over a generic
  terminal app.
- **Look at the Zero's own LED** (the tiny RGB LED between the BOOT and
  RESET buttons). Red means the firmware is running but can't reach the
  sensor — a wiring problem, not a dead board. Off means either all is
  well (the ring should be purple) or the firmware isn't running at all.

## The blue wire doesn't seem to do anything

That's expected. The blue lead (the sensor's touch/WAKEUP output) lands on
`GP8` (GPIO8), but the firmware ships with `DT_USE_WAKEUP_PIN 0` in
`firmware/dashtouch/config.h`: it polls the sensor over the UART every
150 ms instead of waiting on the wake line, because some modules hold that
line at the "active" level all the time. Touch detection never depends on
the blue wire unless you flip that define to 1 and reflash.

## Getting the board into download mode

`./setup`, `dashtouch pairing` and the helper all look for
`/dev/cu.usbmodem*` ports. A Zero running Dashboard Touch firmware shows up
there as an Espressif device (not an Adafruit one), and reflashing it needs
no buttons: the upload opens the port at 1200 baud, and the firmware takes
that as its cue to reboot into download mode.

A brand-new board, or one whose firmware has crashed, may not show up at
all. Put it into download mode by hand:

1. Unplug the USB cable.
2. Hold the **BOOT** button, plug the cable back in, then release BOOT.
   (Cable already connected? Hold BOOT, tap **RESET**, release BOOT.)
3. `ls /dev/cu.usbmodem*` — the board is the port that just appeared.
4. `./setup --port /dev/cu.usbmodemXXXX`, or
   `.venv/bin/dashtouch pairing --port /dev/cu.usbmodemXXXX` for a reflash.
5. The board should restart by itself when the upload finishes. If it
   doesn't come back within a few seconds (no port, ring dark), press
   **RESET** once — a board put into download mode by hand sometimes
   needs that nudge to leave it.

After that first flash, the firmware handles later reflashes by itself.

## It matches (green!) but nothing types

- Is the helper running? `.venv/bin/dashtouch run` in a terminal, or
  `.venv/bin/dashtouch install-agent` to make it permanent.
- A **steady yellow ring** after the green means exactly this: the device
  matched you, then couldn't reach the Mac side.
- Check the log: `cat ~/Library/Logs/dashtouch/helper.log`

## It types the wrong password

The Keychain copy is stale — you probably changed your Mac password (or
it ended up somewhere it shouldn't have, and you already changed it).
Either way: `.venv/bin/dashtouch password`. It prompts you twice,
hidden, and updates only the Keychain entry — nothing else about your
setup changes, and the fix takes effect on your very next touch with no
restart needed. (`./setup` also works, but it's the sledgehammer — it
regenerates the pairing key too and expects a reflash. Reach for
`dashtouch password` first.)

If your password ended up typed somewhere it shouldn't — a chat, a
shared screen, anywhere synced or logged — treat that old password as
burned. Change it in System Settings, then run the command above right
away.

## Fingerprints stopped working after setup

This is a pairing mismatch, not a fingerprint problem — your prints are
still safe on the sensor. It happens when the pairing key changed
Mac-side (via `.venv/bin/dashtouch pairing`, or a re-run of `./setup`)
but the firmware never got reflashed with it. The Checkup's Pairing row
will show red, and every touch's signature gets silently rejected.

Fix: `.venv/bin/dashtouch pairing` walks you through generating a fresh
key and reflashing in one go — run it again if you skipped the flash
step the first time, or flash by hand with the commands it prints.

## Enrolling keeps failing

- Cover the whole ring with the flat pad of your finger, not the tip.
- Same finger both times — the sensor compares the two presses.
- Wet, dusty, or freshly-lotioned fingers read poorly.

## "More than one board is plugged in"

Other USB serial devices (`/dev/cu.usbmodem*`) make the helper unsure which
one is Dashboard Touch. Unplug the others, or tell the helper which port is
yours. Find it with `ls /dev/cu.usbmodem*` (unplug yours and run it again —
the one that disappears is it), then:

```bash
.venv/bin/dashtouch run --port /dev/cu.usbmodem1101
.venv/bin/dashtouch install-agent --port /dev/cu.usbmodem1101   # for the login item
```

The name can change if you move the board to another USB port, in which case
run `install-agent --port` again with the new one. If you actually run two
Dashboard Touch boards, pass `.venv/bin/dashtouch --serial <which>`.

`./setup` and `dashtouch pairing` only choose which board to flash: they ask
when there's more than one, and `--port` skips the question. They don't tell
the running helper which board to use — that's `run --port` / `install-agent
--port` above. The [README](../README.md#if-you-have-other-usb-serial-devices)
has the same steps in order.

## The firmware won't compile

`./setup` only installs the ESP32 Arduino core when none is present, so a
Mac that already had an older core keeps it. This firmware was validated
with core 3.3.12; an error such as `rgbLedWriteOrdered was not declared`,
or a complaint about an unknown board option, means the installed core
predates it. Update it and re-run `./setup`:

```bash
arduino-cli core update-index
arduino-cli core install esp32:esp32@3.3.12
```

## Still stuck?

`firmware/diagnostics/` is a whole toolbox of tiny test programs with
their own README — loopback tests, raw sensor probes, a ring-color
survey. They exist because this build needed every one of them once.
