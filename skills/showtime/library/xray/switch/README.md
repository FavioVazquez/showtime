# Snap-action switch (an old keyboard key, a microswitch, a light switch)

Parts: the lever (the key presses its tip), its pivot on the post, the over-centre spring from the lever's tail to
the contact blade, the moving contact on the blade, the fixed contact. In the panel, a circuit with a lamp.

- An event = a click: the spring's line of action crosses the pivot (dead centre) and the blade snaps, peaking on
  the event's frame. Presses and releases alternate, starting with a press; `"kinds": {"<i>": "release"}` fixes one.
- When the switch is visible in the clip (a cut-away, a bare switch), the in-place view marks the real parts (the
  pivot, the spring's line of action, the contact flashing on each snap) instead of redrawing them; the panel draws
  the schematic and the circuit, lit while the contacts are closed.
- Anchors to place on the reference frame: `pivot`, `contact`, `base_left`, `base_right`.
- Measured: click times and count (the clip's sound). Drawn: a generic snap-action switch; press or release is
  inferred from the order of the clicks.

Verified on: a 1959 keyboard switch, close up ("Clicking a 1959 Cherry mechanical keyboard switch", LGR, Wikimedia
Commons, CC BY 3.0): https://commons.wikimedia.org/wiki/File:Clicking_a_1959_Cherry_mechanical_keyboard_switch.webm
