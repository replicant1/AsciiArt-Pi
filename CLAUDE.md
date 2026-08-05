# ASCII ART

## Project Workflow


### Raspberry Pi file system mounted with SSHFS

This is the local project directory for the "AsciiArt" project. This project is written in Python 3 and runs on the Raspberry Pi Zero 2. The file system for the raspberry pi has been mounted at ../remote using SSHFS. This mount point has been provided to enable AI agents to create, edit and delete files on the Pi through the mount point. ANy changes you make inside it  happen instantly on the Pi. This is necessary because AI agents take more resources to run than are available on the raspberry pi zero 2, so we run the AI agent on this Mac and then let it deploy and modify code etc. to the Pi via the mount point.

The "instantly" above holds for the Mac-to-Pi direction, which is the one that matters for deploying code: write a file into ../remote and the Pi sees it straight away. The reverse direction is NOT always instant. When something running on the Pi writes or modifies a file out-of-band (i.e. not through the mount - a program's output file, or a grim screenshot), a read through ../remote immediately afterwards can return a stale cached version. This was measured: a line appended on the Pi over SSH was missing from the very next read through the mount, then present a moment later, with the sizes agreeing afterwards. Nothing is lost, the cache just lags.

So when reading back a file the Pi just produced, especially a screenshot, do not trust a single immediate read. If a screenshot looks wrong, empty, truncated or suspiciously identical to a previous one, re-read it before concluding anything about the app, and cross-check the size seen through the mount against the Pi:

    stat -f '%z bytes' ../remote/<file>                       # as seen on the Mac
    run_on_pi.sh "stat -c '%s bytes' /home/rod/Projects/AsciiArt/<file>"

Having the Pi-side script finish before the read (as the screenshot recipe below does) plus the natural gap between agent tool calls is usually enough for the cache to catch up, which is why this rarely bites in practice.

The scripts mountpi.sh and unmountpi.sh in ~/rodneybailey can be used to mount and unmount the pi file system from this Mac.

### Commands to Raspberry Pi using SSH

There is also a script called run_on_pi.sh that is in ~/rodneybailey. That script uses the "-t" flag to "ssh" force a pseudo-terminal allocation, which ensures interactive commands, progress bars, and colored terminal ou tputs pass back to the AI correctly. The AI agent should pass whatever commands it wants to execute on the Pi as an argument to the run_on_pi.sh script.

Gotcha - do NOT run "pkill -f <pattern>" over SSH if <pattern> appears anywhere in the command string being sent. run_on_pi.sh passes the whole command to a remote bash, so that bash's own command line contains the pattern, pkill matches it, and the SSH session kills itself. The symptom is exit code 255 with no output, and the intended cleanup silently never happens.

For example, both of these self-destruct because "show_hello" is present in the command line:

    pkill -f show_hello.sh
    pkill -f '[s]how_hello' ; rm -f /home/rod/Projects/AsciiArt/show_hello.sh

Instead, either put the pkill in its own call with a self-excluding bracket pattern and no other mention of the name:

    pkill -f '[s]how_hello'

or avoid pkill entirely - kill by PID, or have the launched script exit on its own (e.g. end it with a "sleep N" so the window closes itself after the screenshot).

### Passwordless SSH (required for the agent)

Both run_on_pi.sh and mountpi.sh connect as rod@192.168.x.x. The Pi accepts "publickey,password", and the AI agent cannot type a password at an interactive prompt, so SSH key auth MUST be set up or every command to the Pi fails with:

    rod@192.168.x.x: Permission denied (publickey,password).

The Mac's public key was installed on the Pi with a one-time command run by the user:

    ssh-copy-id -i ~/.ssh/id_ed25519.pub rod@192.168.x.x

After this, run_on_pi.sh works unattended and mountpi.sh no longer prompts for a password.

Note that an existing SSHFS mount staying alive does NOT mean SSH auth works - the mount keeps using the session it was created with, so run_on_pi.sh can fail with "Permission denied" while ../remote is still readable. Diagnose with:

    ssh -v -o BatchMode=yes rod@192.168.x.x "echo OK"

If the key ever stops being accepted (e.g. the Pi is reimaged, or ~/.ssh/authorized_keys on the Pi is cleared), re-run the ssh-copy-id command above. The agent should ask the user to run it, since it needs the password once. Never ask the user to paste the password into the conversation.

### Screenshots

The AI agent can take screenshots of the raspberry pi screen in order to get feedback on whether the UI of an app looks as expected. It does this by issuing the command "grim <output-file>" where <output-file> is the filename of the resulting screenshot. Note that the filename is a positional argument: grim's "-o" flag selects which monitor to capture, NOT the output file, so "grim -o <output-file>" fails with "unknown output". If this output file is located somewhere within the mounted part of the pi file system the agent can read that file as if it was a local one.

grim captures the Wayland/HDMI output ONLY. It cannot see the ILI9341 SPI display, which is not part of that output at all - see "The 2.4 inch ILI9341 SPI display" below. Nothing drawn on that panel can be verified by screenshot.

### Capturing a program's output in a screenshot

Important: output from a program run via run_on_pi.sh goes to the agent's SSH session and NEVER appears on the Pi's physical display, so a screenshot taken afterwards shows nothing of it. To make output visible to grim, the program must run inside a terminal window on the Pi's own desktop session.

grim also needs the Wayland session's environment, which an SSH session does not inherit. run_on_pi.sh only exports DISPLAY=:0, which is for X11 and is not enough. Set these for grim and for any GUI app being launched:

    export XDG_RUNTIME_DIR=/run/user/1000
    export WAYLAND_DISPLAY=wayland-0

(Confirm the socket name with "ls /run/user/1000 | grep wayland" if it ever differs.)

The working recipe uses two throwaway scaffolding scripts written to the Pi through the mount, which sidesteps the nested-quoting mess of passing a "bash -c '...'" string through ssh:

1. An inner script that the terminal window runs, e.g. show_output.sh:

        #!/bin/bash
        cd /home/rod/Projects/AsciiArt
        python3 hello.py
        sleep 120

   The trailing "sleep" is what holds the window open long enough to be photographed; without it the terminal closes instantly and the screenshot catches an empty desktop. It also makes the window close itself afterwards, so no pkill is needed (see the pkill gotcha above).

2. An outer script that launches the window, waits for it to render, and shoots, e.g. demo_shot.sh:

        #!/bin/bash
        export XDG_RUNTIME_DIR=/run/user/1000
        export WAYLAND_DISPLAY=wayland-0
        lxterminal --title="AsciiArt Demo" -e bash /home/rod/Projects/AsciiArt/show_output.sh &
        sleep 5
        grim /home/rod/Projects/AsciiArt/shot.png

Then run "run_on_pi.sh 'bash /home/rod/Projects/AsciiArt/demo_shot.sh'" and read the PNG through the mount. Give the window a distinctive --title, and have the program print a distinctive string, so the screenshot analysis cannot be fooled by other text already on the desktop.

Files written to the Pi through the SSHFS mount are not executable, so invoke them as "bash <script>" rather than chmod-ing them. lxterminal is the terminal emulator present on this Pi (/usr/bin/lxterminal). An lxterminal AT-SPI dbind-WARNING about "org.a11y.Bus" on startup is harmless noise and can be ignored. Delete the scaffolding scripts when done so they do not clutter the project directory.

### Launching GUI programs (Qt / QtGl / camera preview) over SSH

A GUI program started over SSH WILL appear on the Pi's physical screen, but only if it is given the desktop session's environment. An SSH session does not inherit it. Two variables are needed:

    export XDG_RUNTIME_DIR=/run/user/1000
    export WAYLAND_DISPLAY=wayland-0

DISPLAY=:0 alone (which is all run_on_pi.sh exports) is NOT enough. With both variables set, the window maps straight onto the desktop and grim can photograph it - there is no need to wrap the program in an lxterminal. Wrapping in a terminal is only needed when the terminal TEXT itself has to be visible in the screenshot; for a GUI window, launch it directly:

    nohup python3 -u myapp.py > app.log 2>&1 &

The desktop is labwc (Wayland) with Xwayland running on :0, so Qt apps work through Xwayland with no QT_QPA_PLATFORM setting at all - leave it unset, it was verified working as None.

Timing matters on a Zero 2. The camera preview took roughly 15-20 seconds from process start to a mapped window (libcamera init dominates). A screenshot taken 12 seconds in caught a bare desktop and looked like total failure when the program was in fact fine. Wait at least 25 seconds before concluding a GUI program did not start, and check the log file before believing the screenshot.

### Simulating user input (mouse and keyboard)

The agent CAN drive programs on the Pi with synthetic mouse and keyboard events, which makes it possible to test a GUI app end to end rather than only screenshotting it. This is already set up and verified working.

The mechanism is /dev/uinput: a virtual input device is created in the kernel, so events are indistinguishable from real hardware and reach BOTH Wayland-native and Xwayland clients. (ydotool, the usual Wayland tool, is NOT in this Pi's repos - python3-evdev is used instead.)

Setup already done, and only needed again if the Pi is reimaged:

    sudo apt-get install -y python3-evdev xdotool
    bash /home/rod/Projects/AsciiArt/setup_uinput.sh

setup_uinput.sh loads the uinput module, makes it load at boot via /etc/modules-load.d/uinput.conf, and installs /etc/udev/rules.d/99-uinput.rules giving the "input" group access. User rod is already in that group, so tests do NOT need root.

The helper is /home/rod/Projects/AsciiArt/piinput.py:

    import sys; sys.path.insert(0, "/home/rod/Projects/AsciiArt")
    import piinput
    m = piinput.Mouse();    m.click_at(926, 186)      # absolute screen coords
    k = piinput.Keyboard(); k.type("Hello Pi 42!"); k.key("ENTER")

Both halves are verified: a synthetic click on a window's X button closed it (the app logged its close handler running), and typing into a shell's "read" prompt delivered exactly "Hello Pi 42!" including capitals, digits and shifted punctuation.

Gotchas found the hard way:

- Coordinates are absolute over the whole 2048x1080 screen. To find a target, take a grim screenshot and read the pixel position off it. Remember screenshots are 2048x1080 but may be displayed to the agent scaled down, so scale the coordinates back up before clicking.
- A newly created uinput device needs about a second before the compositor routes events to it. piinput sleeps for this already (SETTLE); do not remove it.
- When building a virtual keyboard, enable only real key codes. Taking every KEY_* name from dir(ecodes) also picks up sentinels like KEY_MAX and KEY_CNT, and UInput then fails with "OSError: [Errno 22] Invalid argument".
- Events go wherever the compositor currently has focus, exactly like real input. Make sure the target window is focused first, and allow time for a freshly launched window to take focus (10s is safe on a Zero 2).
- xdotool is installed too, but it only reaches X11/Xwayland clients and its pointer handling under rootless Xwayland is unreliable. Prefer piinput.
- If a test script launches lxterminal in the background, redirect it (">/dev/null 2>&1 &"). Otherwise the terminal holds the SSH session's stdout open and run_on_pi.sh never returns, which looks like a hang.

### The 2.4 inch ILI9341 SPI display

A second display is attached to the Pi over SPI: a 2.4 inch ILI9341 panel, 240x320 pixels, 65K colours (RGB565). It is separate from, and additional to, the HDMI screen - the ASCII camera can drive both at once.

Wiring, taken from the manufacturer's own working example and confirmed by running it:

    VCC -> 3.3V        SDI/MOSI -> GPIO 10       RESET -> GPIO 27
    GND -> GND         SCK      -> GPIO 11       DC/RS -> GPIO 25
    CS  -> GPIO 8 (CE0)   SDO/MISO -> GPIO 9     LED/BL -> GPIO 18 (PWM dimmable)

The panel is on /dev/spidev0.0. SPI is already enabled ("dtparam=spi=on" in /boot/firmware/config.txt). There is deliberately NO kernel driver bound to it - no fbtft, no mipi-dbi-spi overlay, so it is not a /dev/fb device. It is driven entirely from userspace Python via spidev, which is what src/lcd.py does. /dev/fb0 is the HDMI framebuffer and has nothing to do with this panel.

The manufacturer's reference code (Waveshare) is unpacked at /home/rod/LCD_Module_code/LCD_Module_RPI_code/RaspberryPi/python, with the 2.4 inch driver in lib/LCD_2inch4.py and an example in example/2inch4_LCD_test.py. The project does not depend on it, but its init sequence is known to light this exact hardware and was copied into src/lcd.py rather than re-derived from the datasheet.

**Verification is the hard part, and there is no software answer.** Two independent facts combine:

- grim photographs the Wayland/HDMI output; the SPI panel is not in it.
- This module does not wire SDO usefully. Register read-back was tried (0x04 RDDID, 0x09 RDDST, 0x0A power mode, 0x0C pixel format) and every one returns all 00.

So NOTHING can confirm what is actually lit on the panel except asking the user to look at it. Write tests so the automated part still genuinely can fail - hand-computed RGB565 values, geometry assertions, "does the panel path choose the same glyph the terminal would" - and then print a distinctive, specific description of what should be on screen and ask the user to confirm that exact thing. Never report a panel change as verified on the strength of a clean run.

Code, all committed:

    src/lcd.py           ILI9341 driver over spidev; PIL images or pre-packed RGB565
    src/lcd_display.py   ASCII grid -> panel, via a pre-rendered glyph atlas
    src/lcd_worker.py    background thread so SPI stays off the main render loop
    tests/lcd_selftest.py      colour bars + RGB565 maths (run this first if suspicious)
    tests/lcd_render_bench.py  render path correctness and timing
    tests/lcd_concurrency.py   proves the SPI write does not stall the main loop

Run it with:

    bash run_ascii_camera.sh fit --lcd
    bash run_ascii_camera.sh fit --lcd --colour

Performance facts measured on this Pi, worth not rediscovering:

- /sys/module/spidev/parameters/bufsiz is 4096, so a full 240x320 RGB565 frame (153,600 bytes) is 38 writes. Transfer costs ~32 ms; that dominates, not the clock rate. Raise it with "spidev.bufsiz=65536" on the kernel command line if refresh rate ever matters more than memory.
- Drawing costs only ~3.7 ms of CPU (glyph blit 1.2, RGB565 pack 2.4). Do NOT draw text with one PIL draw.text() per cell - at 64x24 that is 1,536 calls per frame. src/lcd_display.py pre-renders each glyph once and builds a frame as a single numpy gather.
- spidev DOES release the GIL during the transfer, so a worker thread genuinely overlaps: the main thread keeps 93% of its throughput while the panel runs at 27 fps. tests/lcd_concurrency.py measures this rather than assuming it.
- Font sizes 6, 8 and 9 (DejaVu Sans Mono) each tile 320x240 exactly AND give a character grid whose on-screen aspect is exactly 4:3, matching the camera - so filling the panel crops nothing. They give 80x30, 64x24 and 64x20 respectively. 8 is the default.

A caution learned here: synthetic keypresses via piinput proved unreliable for toggling app settings during this work - the first keystroke after creating the device was dropped, and later ones were delivered twice, silently toggling a setting on and back off. Prefer launching the app with the command-line flag you want to test; it is deterministic. See also the piinput gotchas above.

### The KY-040 rotary encoder

A rotary encoder knob is wired to the Pi and cycles the app's colour schemes. It is a third piece of hardware alongside the camera and the SPI panel, and unlike the panel it CAN be verified from here - its effects land in the log.

    CLK -> GPIO 19        + -> 3.3V
    DT  -> GPIO 26      GND -> GND
    SW  -> GPIO 6

Turning cycles the schemes both ways; pressing jumps straight back to grey. Off unless asked for: "bash run_ascii_camera.sh fit --lcd --encoder". Driven from userspace via lgpio (installed; gpiozero and RPi.GPIO are present too, pigpio is NOT). Code is src/encoder.py, tests are tests/encoder_test.py, and tools/probe_encoder.py finds the pins.

GPIO 6 for SW was chosen deliberately, not just because it was free. The module fits no pull-up on SW, so it relies on the internal one, and this chip defaults GPIO 0-8 to pull-UP but 9-27 to pull-DOWN. On a pull-down pin the switch reads as held down from power-on until the app configures it; on GPIO 6 it idles high throughout. Apply the same reasoning to any future switch.

Finding the pins again, if the wiring is ever changed: the module has its own pull-ups on CLK and DT, so those two pins read high in "pinctrl get 0-27" even though this chip defaults GPIO 9-27 to pull-DOWN. That narrows it to two candidates but does not confirm them, and it cannot see SW at all (no pull-up is fitted there). Run tools/probe_encoder.py and turn the knob; it identifies the pair by which pins interleave, which is a property two merely noisy pins do not have.

Two things measured here that are worth not rediscovering:

- The contacts bounce about 5:1 - twenty clicks gave 453 edges, 88 after a 1 ms debounce. Do NOT decode by counting edges or by sampling the partner pin at each edge; both read bounce as movement. src/encoder.py uses a quadrature transition table that only emits on a complete cycle, which ignores bounce by construction. One detent is one full cycle on this module.
- Applying banked detents one at a time causes a violent strobe and tanks the frame rate. Every scheme change calls display.set_scheme(), which ends in stdscr.clear() and repaints all ~27,000 cells, so a five-detent spin became five full repaints between two frames - four of them of pictures never on screen long enough to see. It feeds back on itself, because a slower frame banks more detents. _cycle_scheme takes the whole move at once and repaints once. A two-detent move writing a single "Scheme:" log line is the check that this still holds.

Which direction is "forwards" cannot be derived - it depends on which pin was called CLK - so it is resolved by turning the real knob. As wired, clockwise is forwards and --encoder-reverse is off.

Only counts survive between frames, not the order events happened in, so a turn and a press in the same frame gap cannot be told apart from a press and a turn. The press wins and the rotation is dropped: it is the answer that can be checked by looking, since it is the same wherever the knob had got to, and it costs one repaint rather than two.

Do NOT benchmark or restart the app while the user is testing the knob by hand. Doing that here produced a confident "turning the encoder has no visible effect" report from the user, because the benchmark had just relaunched the app WITHOUT --encoder. Get the user's verification first, then measure.

### Installing packages on the Pi (low memory)

The Pi Zero 2 has only ~416 MB of usable RAM and apt can be OOM-killed mid-install, leaving packages half-configured and every later install blocked. This actually happened: apt-listchanges was killed while reading a 28 MB LibreOffice changelog. Always disable it:

    sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Use-Pty=0 <packages>

If apt reports unmet dependencies for unrelated packages, the package state is already broken and NO install will work until it is repaired:

    sudo apt-get clean                      # if a .deb failed with "unexpected end of file or stream"
    sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive apt-get --fix-broken install -y

Large installs can take many minutes on this hardware. Run them in the background rather than polling in a tight loop, and note that an SSH exit code of 255 usually means the connection dropped, not that the install failed - check with dpkg or by importing the module before concluding anything.

## Directory Summary

There are THREE sibling directories under /Users/rodneybailey/PiProjects/AsciiArt, and the git repository is the one that is easiest to overlook:

    remote/        the Pi's /home/rod/Projects/AsciiArt, over SSHFS - the deployed code that actually runs
    local/         Mac-only working notes, and the unredacted original of this file. Not mirrored to the Pi.
    AsciiArt-Pi/   THE GIT REPOSITORY. Remote: git@github.com:replicant1/AsciiArt-Pi.git

Raspberry Pi directory: /home/rod/Projects/AsciiArt
Mac mount point: /Users/rodneybailey/PiProjects/AsciiArt/remote
Local files (including this one. not mirrored on pi): /Users/rodneybailey/PiProjects/AsciiArt/local
Git repository (NOT inside the mount): /Users/rodneybailey/PiProjects/AsciiArt/AsciiArt-Pi

Neither remote/ nor local/ is a git repository, and running git in either fails with "not a git repository". For any commit, branch or PR request, work in AsciiArt-Pi.

The repo is kept off the mount on purpose: git does constant read-after-write against its own object store, and reads back through SSHFS can return stale data when the Pi has written out of band (see the caching note at the top of this file). Handing git a filesystem that can lie to it is not worth the convenience.

Code moves between the two with AsciiArt-Pi/sync.sh:

    bash sync.sh            # or "pull": Pi mount -> repo, ready to commit
    bash sync.sh push       # repo -> Pi mount, e.g. after a git pull
    bash sync.sh status     # report differences, copy nothing

The normal workflow is therefore: edit code on the Pi through remote/ so the running deployment stays the source of truth, test it there, then "bash sync.sh pull" and commit in AsciiArt-Pi.

Two traps in sync.sh:

- It copies ONLY files named in its explicit ROOT_FILES / SRC_FILES / TEST_FILES / DOC_FILES arrays. A newly added module must be added to the right array or it is silently never synced - no error, it simply never appears in the repo. Adding a file to the project means editing sync.sh in the same change.
- "sync.sh pull" regenerates the repo's CLAUDE.md from local/CLAUDE.md with the Pi's IP address masked. Always edit local/CLAUDE.md, never the repo's copy, and never push CLAUDE.md back to the Pi.

## Script Summary

Restore passwordless SSH to the pi (user must run it, needs the password once): ssh-copy-id -i ~/.ssh/id_ed25519.pub rod@192.168.x.x
Simulate mouse/keyboard input on pi: import /home/rod/Projects/AsciiArt/piinput.py (see "Simulating user input" above)
Re-enable input simulation after a reimage: bash /home/rod/Projects/AsciiArt/setup_uinput.sh
Mount the pi as above: /Users/rodneybailey/mountpi.sh
Unmount the pi from above: /Users/rodneybailey/unmountpi.sh
Run a command on pi using SSH: /Users/rodneybailey/run_on_pi.sh
Take a screenshot on pi (HDMI output only - NOT the SPI panel): Call the run_on_pi.sh script with the argument "grim <output-file>" where <output-file> is somewhere within the mounted filesystem of the pi.
Run a python file on the pi: Call the run_on_pi.sh script with the argument "python3 <filename.py>" where <filename.py> is the python file you want to run
Move code between the Pi and the git repo: bash /Users/rodneybailey/PiProjects/AsciiArt/AsciiArt-Pi/sync.sh [pull|push|status]
Launch the ASCII camera on the Pi's HDMI screen: bash /home/rod/Projects/AsciiArt/run_ascii_camera.sh fit
Launch it on the HDMI screen and the ILI9341 panel together: bash /home/rod/Projects/AsciiArt/run_ascii_camera.sh fit --lcd
Check the ILI9341 panel is alive (colour bars, needs a human to confirm): python3 /home/rod/Projects/AsciiArt/tests/lcd_selftest.py
Launch it with the rotary encoder cycling the colour schemes: bash /home/rod/Projects/AsciiArt/run_ascii_camera.sh fit --lcd --encoder
Find which GPIO pins the rotary encoder is on (needs a human to turn the knob): python3 /home/rod/Projects/AsciiArt/tools/probe_encoder.py
Check the rotary encoder decode without any hardware: python3 /home/rod/Projects/AsciiArt/tests/encoder_test.py
