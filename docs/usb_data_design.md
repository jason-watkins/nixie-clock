# USB data link design

Status: future work, targeted at a revision after Rev A. No part of this
design is present in Rev A.

## Summary

The USB-C port carries a USB 2.0 full-speed device link to the MCU in
addition to its power roles. The power architecture of psu_design.md is
unchanged: the sink controller alone decides when the board receives
power, the bucks and the flyback sit downstream of the load switch, and
the flyback's undervoltage lockout keeps the anode rail off below 8.1 V
input. The additions are one strap change on the sink controller, an
analog multiplexer on D+/D−, and a rail-sense divider for the MCU.

Behavior by source type:

| Source | Rail | Result |
|---|---|---|
| Power Delivery 12 V or 9 V | 12 V / 9 V | full clock operation |
| Quick Charge or Adaptive Fast Charging brick | 12 V / 9 V | full clock operation |
| PC port or 5 V charger | 5 V | logic runs, tubes dark, USB link live |
| No contract (bad source) | none | board off |

On a 5 V source the MCU enumerates through the ESP32-S3's on-die
USB-Serial-JTAG peripheral: flashing, console, and JTAG debug over the
same cable that powers the board, with no bridge silicon. The high
voltage rail cannot start at 5 V regardless of firmware state, because
the flyback's undervoltage lockout holds the converter off independent
of everything in this document.

## Sink controller strap change

VBUS_MIN moves from 9 V to 5 V: pull-up open, pin strapped to ground
(the pin reads below 249 mV, encoding a 5 V minimum). VBUS_MAX stays
12 V, so the controller still takes the highest offer up to 12 V from
Power Delivery and legacy sources alike. With a 5 V minimum, the
negotiation cascade (Power Delivery, then BC1.2, Adaptive Fast Charging,
Quick Charge 2.0, Apple, then Type-C default) terminates successfully at
5 V on a standard downstream port and closes the load switch.

The FAULT indicator narrows in meaning: a 5 V source is now a
successful contract, so the LED reports only genuine failures (no
agreement, voltage out of window, overvoltage, sink overcurrent).

At a 5 V contract the current budget is whatever the source advertises,
500 mA from a standard downstream port. The sink controller does not
enforce sink-side current, so firmware keeps the radio duty cycle low
whenever the rail-sense divider reads 5 V.

## D+/D− multiplexer

The charger handshakes and the USB device link both require exclusive
use of D+/D−, so a 2:1 analog multiplexer arbitrates the pair (the
TS3USB221A class fits: USB-2.0-rated switch, 30 µA supply-current
ceiling, 3.3 V supply). The connector's commoned D+/D− pins route through the
existing electrostatic-discharge diodes at the connector to the
multiplexer common port; one branch goes to the sink controller's D+/D−
pins, the other to MCU GPIO19/20, which are the USB peripheral's data
pins.

**Supply.** The multiplexer runs from the sink controller's VDDD pin at
all times; there is no handoff to the board's 3.3 V rail. VDDD is the
controller's internal 3.3 V regulator output, alive whenever VBUS is
present, before the load switch closes. This matters at cold attach on
a Quick Charge or Adaptive Fast Charging brick: the D+/D− handshake
happens while the rest of the board is dark, and since the controller's
own logic runs from the same regulator, the multiplexer cannot come up
after it.

The load this places on VDDD is bounded by the switch's 30 µA
supply-current limit, which is specified with the switch on: handshake
and USB drive current flows from the D+/D− drivers through the switch
path and returns to the drivers, never through the supply pin, so the
figure does not rise during negotiation or data transfer. A control
input held at mid-rail adds up to 20 µA, so the select pull resistor
ties to ground rather than a divider and the MCU drives it rail to
rail. Worst case is 50 µA against a regulator that already feeds about
1 mA of continuous strap-divider drain and several milliamps through
the FAULT pin when the LED is lit, with the chip's own 10 mA active
draw behind the same regulator input.

**Select.** A pull resistor defaults the select to the controller
branch; an MCU GPIO drives it to claim the port. Firmware claims USB
only when the rail-sense divider reads about 5 V. At 9 V or 12 V the
source is a charger with no host behind it, and its handshake completed
before the MCU booted, so there is nothing to claim. At 5 V the
handshake concluded before the load switch closed, and the controller
no longer needs the pair.

**Recovery.** With firmware dead the select stays on the controller
branch and the USB link is unreachable. The recovery flash path is
UART0: hold the boot-strap button, pulse reset, flash over serial. The
multiplexer places no constraint on that path.

**Layout.** Full-speed signaling at 12 Mbps: route the pair short and
loosely matched, minimize the stub from the multiplexer to each branch,
and keep the discharge diodes at the connector where they are. No
controlled impedance is required at this speed on a board this size.

## Rail-sense divider

A divider from the switched rail to an MCU analog input reads the
contract voltage: 100 kΩ over 18 kΩ gives 1.83 V at 12 V, 1.37 V at
9 V, and 0.76 V at 5 V, and holds a 20 V bus fault under the 3.6 V pin
limit. A 100 nF capacitor at the pin serves the converter's sampling.
The reading drives the multiplexer claim policy, the radio duty
decision, and gives firmware sight of which contract the controller
landed.

## Statements in psu_design.md this design replaces

- The VBUS_MIN row of the strap table (9 V, 5.1 k / 1 k) becomes 5 V,
  open / short.
- "On a plain 5 V charger the board stays off rather than browning out"
  becomes: on a 5 V source the logic runs and the flyback stays in
  lockout.
- "D+ and D− route from the connector to the chip" gains the
  multiplexer between the connector and the chip.
- The FAULT description ("asserts on any failed or lost contract")
  narrows as described above, since a 5 V-only source no longer fails.

Everything else in psu_design.md stands, in particular the load switch,
the protection network, the flyback undervoltage lockout, and the
placement of both bucks downstream of the load switch.
