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

### Installing packages on the Pi (low memory)

The Pi Zero 2 has only ~416 MB of usable RAM and apt can be OOM-killed mid-install, leaving packages half-configured and every later install blocked. This actually happened: apt-listchanges was killed while reading a 28 MB LibreOffice changelog. Always disable it:

    sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Use-Pty=0 <packages>

If apt reports unmet dependencies for unrelated packages, the package state is already broken and NO install will work until it is repaired:

    sudo apt-get clean                      # if a .deb failed with "unexpected end of file or stream"
    sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive apt-get --fix-broken install -y

Large installs can take many minutes on this hardware. Run them in the background rather than polling in a tight loop, and note that an SSH exit code of 255 usually means the connection dropped, not that the install failed - check with dpkg or by importing the module before concluding anything.

## Directory Summary

Raspberry Pi directory: /home/rod/Projects/AsciiArt
Mac mount point: /Users/rodneybailey/PiProjects/AsciiArt/remote
Local files (including this one. not mirrored on pi): /Users/rodneybailey/PiProjects/AsciiArt/local

## Script Summary

Restore passwordless SSH to the pi (user must run it, needs the password once): ssh-copy-id -i ~/.ssh/id_ed25519.pub rod@192.168.x.x
Simulate mouse/keyboard input on pi: import /home/rod/Projects/AsciiArt/piinput.py (see "Simulating user input" above)
Re-enable input simulation after a reimage: bash /home/rod/Projects/AsciiArt/setup_uinput.sh
Mount the pi as above: /Users/rodneybailey/mountpi.sh
Unmount the pi from above: /Users/rodneybailey/unmountpi.sh
Run a command on pi using SSH: /Users/rodneybailey/run_on_pi.sh
Take a screenshot on pi: Call the run_on_pi.sh script with the argument "grim <output-file>" where <output-file> is somewhere within the mounted filesystem of the pi.
Run a python file on the pi: Call the run_on_pi.sh script with the argument "python3 <filename.py>" where <filename.py> is the python file you want to run
