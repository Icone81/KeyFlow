# KeyFlow

**KeyFlow** is a lightweight Windows desktop automation tool for
creating reusable sequences of keyboard presses, key combinations, mouse
movements, mouse clicks, and timed waits. Assign each sequence a global
hotkey, run it on demand, or enable an independent loop for repeated
execution.

Instead of writing a script for every repetitive desktop task, build and
manage sequences through a graphical editor.

## Features

-   **Global hotkeys** --- trigger each sequence from anywhere in
    Windows.
-   **Visual sequence editor** --- create, edit, remove, and reorder
    actions.
-   **Six action types** --- key press, key combination, move and click,
    move mouse, click at current position, and wait.
-   **Per-sequence looping** --- enable or disable looping independently
    for each hotkey.
-   **Quick stop** --- press the active sequence's hotkey again, or use
    the Stop button, to request that execution stop.
-   **Random waits** --- add a random delay within a configurable
    minimum and maximum.
-   **Coordinate capture** --- capture mouse coordinates with an
    on-screen overlay. The capture works across multiple monitors.
-   **JSON configuration** --- save sequences locally and load
    configurations from other JSON files.
-   **System tray integration** --- hide the editor in the notification
    area and restore it when needed.
-   **Windows startup** --- optionally launch KeyFlow minimized to the
    system tray when signing in.
-   **Live theme editor** --- change the application's color palette and
    preview changes immediately.
-   **DPI and multi-monitor support** --- uses Windows monitor
    information and per-monitor DPI awareness for coordinate handling.

## Screenshots

<img width="798" height="723" alt="image" src="https://github.com/user-attachments/assets/82917d04-8d59-467a-a380-1cfbb303d7fc" />

## Requirements

-   Windows (the application uses Windows APIs and is designed for
    Windows desktops).
-   Python 3.9 or later is recommended.
-   Tkinter, normally included with the standard Windows Python
    installation.

### Python dependencies

Install the required and optional packages with:

``` bash
python -m pip install keyboard pydirectinput
```

For system tray support and the enhanced graphics used by the interface,
install:

``` bash
python -m pip install pystray Pillow
```

`pystray` and `Pillow` are optional. Without them, the main editor and
sequence execution can still be used, but system tray integration is
unavailable and some visual elements use simpler rendering.

## Getting started

1.  Clone or download this repository.

2.  Install the dependencies listed above.

3.  Run the application:

    ``` bash
    python keyflow.py
    ```

4.  Create a sequence using **+ New** and assign it a hotkey, for
    example `f8` or `ctrl+alt+1`.

5.  Select the sequence and use **+ Add** to add actions.

6.  Save the configuration.

7.  Trigger the sequence with its hotkey, or select it and click **Run
    sequence**.

To start the application minimized to the system tray:

``` bash
python keyflow.py --tray
```

The `--tray` argument only requests tray startup; tray support must be
available.

## How it works

### 1. Sequences and hotkeys

A sequence is an ordered list of actions associated with a hotkey.
KeyFlow registers each configured hotkey globally, so it can be
triggered while another application is in the foreground.

Actions run from top to bottom. Only one sequence can execute at a time.
If a sequence is running, pressing its own hotkey requests that it stop;
other sequence hotkeys are ignored until the current execution ends.

The **Enable hotkey sequences** switch controls hotkey-triggered
execution. Turning it off does not disable the **Run sequence** button
in the editor.

Hotkeys are registered without suppressing the original key event. The
hotkey may therefore also be received by the foreground application.

### 2. Available actions

  -----------------------------------------------------------------------
  Action                  What it does            Configuration
  ----------------------- ----------------------- -----------------------
  **Key press**           Presses and releases    A key name, such as
                          one key.                `b`, `enter`, or
                                                  `space`.

  **Key combination**     Presses multiple keys   A comma-separated list,
                          together, then releases such as
                          them in reverse order.  `ctrl, shift, s`.

  **Move and click**      Moves the pointer to a  X, Y, and mouse button.
                          coordinate and clicks.  

  **Move mouse**          Moves the pointer       X and Y coordinates.
                          without clicking.       

  **Click at current      Clicks wherever the     Mouse button.
  position**              pointer currently is.   

  **Wait**                Pauses before           A fixed number of
                          continuing.             seconds, or a random
                                                  minimum/maximum range.
  -----------------------------------------------------------------------

The supported mouse buttons are `left`, `right`, and `middle`.

For coordinate-based actions, use **GRAB coordinates** to capture the
current pointer position. Move the pointer to the target and left-click
to confirm. Press `Esc` or right-click to cancel.

### 3. Loop mode

Loop mode is configured separately for every sequence.

-   **Loop off:** the sequence runs once and finishes.
-   **Loop on:** the full sequence repeats until stopped.
-   **Stop a loop:** press the same hotkey again or click **Stop** in
    the editor.

While a loop is running, KeyFlow displays a small desktop overlay
showing the active hotkey and current cycle number.

A wait action inside a loop is useful for controlling the interval
between repeated operations. Random waits are available when a fixed
interval is not desirable.

### 4. Saving and configuration

KeyFlow uses two JSON files in the application's directory:

  -----------------------------------------------------------------------
  File                                Purpose
  ----------------------------------- -----------------------------------
  `keyflow_sequences.json`            Saved hotkey-to-sequence
                                      definitions.

  `keyflow_settings.json`             Application settings, per-sequence
                                      loop preferences, and the saved
                                      color palette.
  -----------------------------------------------------------------------

Use **Save** to write the current sequences to `keyflow_sequences.json`.
Use **Load JSON** to replace the current sequence configuration with
another JSON file.

The application validates loaded sequence data. Invalid configurations
are rejected rather than partially loaded. Writes use a temporary file
followed by an atomic replacement to reduce the risk of corrupting a
configuration during saving.

### 5. System tray and Windows startup

Choose **Hide to tray** to keep KeyFlow running without showing the
editor. The tray menu provides options to:

-   Open the KeyFlow editor.
-   Enable or disable hotkey sequences.
-   Enable or disable **Start with Windows**.
-   Exit the application.

When **Start with Windows** is enabled, KeyFlow creates an entry under
the current Windows user's `Run` registry key. It launches with the
`--tray` argument, so the editor starts hidden when tray support is
available.

### 6. Appearance

Open **Colors** in the status bar to customize the application's theme.
Changes are previewed immediately. Press **Save** in the color editor to
persist the palette in `keyflow_settings.json`.

## Practical examples

The examples below describe sequences you can build in the graphical
editor. Coordinates are illustrative: use **GRAB coordinates** to
capture positions on your own display.

### Example 1: Open a tool and enter a shortcut

**Goal:** Open the Windows Run dialog, type a command, and execute it.

Create a sequence with the hotkey `f8` and add these steps:

    Order Action            Configuration
  ------- ----------------- ---------------
        1 Key combination   `win, r`
        2 Wait              `0.5` seconds
        3 Key press         `n`
        4 Key press         `o`
        5 Key press         `t`
        6 Key press         `e`
        7 Key press         `p`
        8 Key press         `a`
        9 Key press         `d`
       10 Key press         `enter`

This example uses individual key presses because **KeyFlow's Key press
action sends one key, not a text string**. The current version does not
include a dedicated type-text action.

### Example 2: Move to a screen location and click

**Goal:** Move the pointer to a known button and click it.

Create a sequence with the hotkey `f9`:

  ------------------------------------------------------------------------
                         Order Action                Configuration
  ---------------------------- --------------------- ---------------------
                             1 Move and click        Capture the target
                                                     X/Y coordinates;
                                                     choose `left`.

                             2 Wait                  `0.3` seconds.
  ------------------------------------------------------------------------

Use **GRAB coordinates** in the step editor to capture the target
position. This is useful for a stable interface where the target remains
in the same place.

### Example 3: Use a keyboard shortcut, then wait

**Goal:** Save the active document and allow the application time to
respond.

Create a sequence with the hotkey `ctrl+alt+s`:

    Order Action            Configuration
  ------- ----------------- ---------------
        1 Key combination   `ctrl, s`
        2 Wait              `1.0` seconds

You can trigger this sequence from another application without opening
the KeyFlow editor.

### Example 4: Repeat a mouse action

**Goal:** Repeat a click at a fixed location until you stop it.

1.  Create a sequence with the hotkey `f10`.
2.  Add a **Move and click** step and capture the target coordinates.
3.  Add a **Wait** step, for example `2.0` seconds.
4.  Enable **Loop** for this sequence.
5.  Save the configuration.

Press `f10` to start the loop. KeyFlow repeats the two steps and
displays the cycle count in its overlay. Press `f10` again or click
**Stop** to stop it.

### Example 5: Add a variable pause

**Goal:** Repeat an action with a delay that varies between cycles.

1.  Create a sequence and add the actions you want to repeat.
2.  Add a **Wait** step.
3.  Enable **Random duration**.
4.  Set a minimum of `1.0` seconds and a maximum of `3.0` seconds.
5.  Enable **Loop** for the sequence.

Each time the wait step is reached, KeyFlow chooses a new duration
between the configured bounds.

## JSON configuration example

The following is a small example of the structure used by
`keyflow_sequences.json`:

``` json
{
  "f8": [
    {
      "type": "combo",
      "keys": ["ctrl", "s"]
    },
    {
      "type": "wait",
      "seconds": 1.0
    }
  ],
  "f9": [
    {
      "type": "move_click",
      "x": 800,
      "y": 600,
      "button": "left"
    },
    {
      "type": "wait",
      "random": true,
      "min": 1.0,
      "max": 3.0
    }
  ]
}
```

Loop preferences are stored separately in `keyflow_settings.json`, not
in the sequence definitions.

## Building a Windows executable

KeyFlow can be run directly from Python. If you want to distribute it as
a Windows executable, PyInstaller can be used.

Install PyInstaller:

``` bash
python -m pip install pyinstaller
```

A typical one-file build command is:

``` bash
pyinstaller --noconfirm --onefile --windowed --name KeyFlow --icon keyflow.ico --add-data "keyflow.ico;." keyflow.py
```

The icon is bundled as a resource for the application windows and system
tray. Keep the generated executable in a writable directory: KeyFlow
stores its JSON configuration and settings alongside the executable.

The executable still bundles the Python runtime and required
dependencies; PyInstaller does not produce a native, interpreter-free
binary.

## Important notes and limitations

-   **Windows only:** the application relies on Windows-specific APIs
    for monitor enumeration, coordinate capture, DPI awareness,
    title-bar styling, and startup registration.
-   **Coordinates depend on the desktop layout:** changing monitor
    arrangement, resolution, scaling, or application layout can
    invalidate saved coordinates. Capture them again if needed.
-   **Use with care:** a sequence sends real keyboard and mouse input to
    the foreground desktop. Review the actions and target application
    before running a loop.
-   **Failsafe behavior:** the current implementation sets
    `pydirectinput.FAILSAFE = False`. Moving the pointer to a screen
    corner will not act as a PyDirectInput failsafe stop. Use the
    sequence hotkey or the editor's **Stop** button.
-   **One sequence at a time:** KeyFlow does not run multiple sequences
    concurrently.
-   **No text-typing action:** the current action set supports
    individual key presses and key combinations, not a dedicated
    arbitrary text-entry step.
-   **Hotkey conflicts:** another application or keyboard utility may
    already use a chosen global hotkey. Choose a different combination
    if it does not trigger as expected.

## Project structure

``` text
KeyFlow/
├── keyflow.py
├── keyflow.ico
├── keyflow_sequences.json   # created when sequences are saved
└── keyflow_settings.json    # created when settings are saved
```

## License

No license is specified in the source provided. Add a `LICENSE` file
before publishing if you want to grant others explicit permission to
use, modify, and distribute the project.
