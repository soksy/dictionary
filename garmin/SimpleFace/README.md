# Simple Face — a Garmin Connect IQ watch face for the Fenix E

A minimal digital watch face written in Monkey C:

- Large centered time (respects the watch's 12/24-hour setting)
- Date line below the time (`Thu, Jul 24`)
- Battery percentage at the top (turns red at ≤ 15%)
- Step count at the bottom
- Black background (kind to the AMOLED panel) and a low-power sleep mode

Everything is positioned relative to the screen size at runtime, so it centers
correctly on the Fenix E's round 416×416 display without hard-coded offsets.

## Project layout

```
SimpleFace/
├── manifest.xml                     # app id, type=watchface, target = fenixe
├── monkey.jungle                    # build config
├── resources/
│   ├── drawables/
│   │   ├── drawables.xml            # declares the launcher icon
│   │   └── launcher_icon.png        # 40×40 icon
│   └── strings/
│       └── strings.xml              # app name
└── source/
    ├── SimpleFaceApp.mc             # application entry point
    └── SimpleFaceView.mc            # the watch face itself (all drawing)
```

## One-time setup on your PC

1. Install **VS Code** and a **Java Runtime (8+)**.
2. Install Garmin's **Connect IQ SDK Manager**, then use it to download the
   latest SDK **and** the Fenix E device. Set the downloaded SDK as active.
3. In VS Code, install the **Monkey C** extension (published by Garmin).
4. Generate a **developer signing key** — command palette →
   `Monkey C: Generate a Developer Key`. Back this file up somewhere safe; you
   need the same key to update the app later. **Do not commit it** (see
   `.gitignore`).

Full walkthrough: <https://developer.garmin.com/connect-iq/connect-iq-basics/getting-started/>

## Run it in the simulator (no watch needed)

1. Open the `SimpleFace/` folder in VS Code.
2. Command palette → `Monkey C: Build for Device` isn't required first — just
   press **F5** (Run → Start Debugging). Pick **fenix E** when prompted.
3. The Connect IQ simulator launches with the watch face running.

## Put it on your Fenix E

**Option A — build a sideload file, then copy it over**

1. Command palette → `Monkey C: Build for Device`. Choose **fenix E**.
   This produces `bin/SimpleFace.prg`.
2. Plug the watch into the computer with its charging/data cable. It mounts as
   a USB drive.
3. Copy `bin/SimpleFace.prg` into the watch's `GARMIN/APPS/` folder.
4. Eject the watch. On the device, open the watch-face picker (hold the
   top-left button, or **Watch Face** in settings) and select **Simple Face**.

**Option B — from the command line** (SDK `bin/` on your PATH):

```bash
# build a signed .prg for the Fenix E
monkeyc -f monkey.jungle -o bin/SimpleFace.prg -y /path/to/developer_key.der -d fenixe

# then copy bin/SimpleFace.prg to the watch's GARMIN/APPS/ folder as in Option A
```

## Notes & next steps

- **Device id:** the target is `fenixe` in `manifest.xml`. To add more watches,
  run `Monkey C: Edit Products` in VS Code, or add `<iq:product id="..."/>`
  lines yourself.
- **App id:** `manifest.xml` ships with a placeholder GUID — fine for personal
  sideloading. Generate a fresh one before publishing to the Connect IQ Store.
- Ideas to extend: an analog hands layout, a seconds display while awake,
  goal/heart-rate complications, or user-configurable colors via
  `resources/settings/`.
