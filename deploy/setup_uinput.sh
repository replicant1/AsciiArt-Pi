#!/bin/bash
# One-time setup so a normal user can create virtual input devices.
# rod is already in the "input" group, so a udev rule granting that group
# access to /dev/uinput is enough - no need to run tests as root.
set -e

sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null   # load at boot

printf 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"\n' \
    | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null

sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput

ls -l /dev/uinput
