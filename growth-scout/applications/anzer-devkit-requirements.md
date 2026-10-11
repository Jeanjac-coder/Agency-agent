For review: ANZER DevKit requirements (call Fri 16 Oct, 9:30am ET)

DRAFT FOR JEREMY. Not sent to ANZER. Fill every {{PLACEHOLDER}} and [bracket] before anything goes to Jay Mendpara. No NDA has been signed or returned. That is a founder decision.

BLUF
We want ANZER to quote and build {{DEVKIT_QTY: 5-10}} Vybe DevKit v0.1 boards: a screenless, wrist-worn overnight band that measures heart rate and heart rate variability and syncs over Bluetooth Low Energy. We need finished, tested boards by {{TARGET_DATE}} so they can go to design partners. The design package is [complete / partly complete; see section 3], and we would like a design-for-manufacturability (DFM) review as part of the quote.

1. TASK: what the board is
- Function: worn on the wrist overnight. It records heart rate, heart rate variability and sleep timing, and the results are read against the wearer's own baseline. There is no screen. Data goes to a phone over Bluetooth Low Energy and from there to the Vybe SDK.
- Sensors: {{SENSOR_SET: optical HR sensor part no., front-end IC, accelerometer/IMU part no., skin-temperature if any}}
- MCU and radio: {{MCU_RADIO: e.g. part no. and BLE version}}
- Power: {{BATTERY: chemistry, capacity mAh, curved cell? supplier if chosen}}, battery-life target {{BATTERY_LIFE_TARGET}}, charging {{CHARGING: contacts / wireless / connector}}
- Form factor: board outline {{BOARD_DIMENSIONS_MM}}, rigid / flex / rigid-flex {{BOARD_TYPE}}, max height {{MAX_Z_MM}}. The band must sit flat and be comfortable through a full night's sleep.
- Enclosure: {{ENCLOSURE_STATE: none / 3D-printed / tooled}}. For DevKit v0.1, ANZER is asked for [board assembly only / board plus box build].

2. CONDITIONS: quantity and timeline
- Phase 1: {{DEVKIT_QTY}} DevKit boards, needed by {{TARGET_DATE}}.
- Phase 2 (if Phase 1 works): a pilot run of {{PILOT_QTY}}, timing {{PILOT_TIMING}}.
- Context only, not a commitment: consumer launch is targeted for May 2027.

3. CONDITIONS: what exists today and what does not
Mark each item ready, in progress or not started.
- Schematic: {{STATUS}}
- PCB layout: {{STATUS}}
- Gerbers / fab files: {{STATUS}}
- BOM with manufacturer part numbers: {{STATUS}}
- Firmware (flashable image): {{STATUS}}
- Mechanical CAD (band/enclosure): {{STATUS}}
- Test fixtures / test procedure: {{STATUS}}
Gaps we already know about: [list them plainly]

4. STANDARDS: build and sourcing
- Turnkey or consigned: {{TURNKEY_OR_CONSIGNED}}. Why: [e.g. turnkey because we have no parts stock; consigned for the sensor and battery if we already hold them]
- Workmanship: IPC-A-610 Class {{IPC_CLASS: 2 or 3}}.
- With delivery we want:
  - continuity and power-on test results per board
  - firmware flashed and version recorded
  - a BLE advertising check
  - the as-built BOM with lot and date codes
  - photos of any rework
  - one sample report from any in-circuit or functional test ANZER runs

5. STANDARDS: regulatory posture
- Vybe is a general wellness product, not a medical device. It makes no diagnostic claims.
- ANZER's ISO 13485 quality system is welcome, but we are not making a device claim.
- Wireless: the boards must be able to pass FCC Part 15 later. For the DevKit we [will / will not] run pre-compliance testing at this stage.

6. WHAT WE NEED BACK FROM JAY
1. Minimum order quantity for a prototype run of this size.
2. Lead time from released files to finished boards.
3. Will you quote from an incomplete design package, and what do you need from us before you can quote?
4. NRE and tooling costs (stencils, fixtures, programming).
5. Component sourcing and lifecycle risk on our BOM, and suggested alternates.
6. Cost difference between turnkey and consigned for this run.
7. Do you do a DFM review, and is it included in the quote or separate?
8. Can you do box build and final assembly of the band, or boards only?

Open questions for Jeremy before the call
- Do you want an NDA in place before sharing the schematic and BOM? (Yours or ANZER's; your call.)
- Which files are you willing to send ahead of Friday?
- Budget ceiling for Phase 1: {{BUDGET}}. Kept internal; not for ANZER.
