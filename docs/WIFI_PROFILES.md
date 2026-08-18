# Multiple Wi-Fi Profiles

Deutsche Fassung: [Mehrere WLAN-Profile](../docs_DE/WIFI_PROFILES.md)

The Raspberry Pi uses NetworkManager for Wi-Fi connections. The ABR tool
`abr.wifi_profiles` therefore does not maintain a separate password file; it
works with NetworkManager's protected connection profiles.

Practically verified as of `2026-08-03`:

- switching from the local router to an iPhone hotspot works
- switching back is also possible through a Raspberry Pi Connect session
- adding a profile is separate from switching connections, so the active SSH
  session remains available while saving it
- at boot and after connection loss, NetworkManager can automatically choose
  from all stored, reachable profiles

## Listing and Adding Profiles

```bash
cd ~/src/abr
sudo .venv/bin/python -m abr.wifi_profiles list
sudo .venv/bin/python -m abr.wifi_profiles add PROFILE_NAME ACTUAL_SSID
```

`add` first prompts interactively for the Wi-Fi password and then creates the
complete NetworkManager profile. Credentials are therefore available before
activation can interrupt the existing SSH connection. The password is not
stored in shell history or in the repository. Profile name and SSID may be
different. Quote names containing spaces.

Important: Names in this guide are placeholders. Run commands individually
with the actual SSID; do not paste an entire example block unchanged. `add`
saves the profile without changing the active connection. Immediate
activation is possible with `--activate`, but may interrupt an SSH session.

An existing Wi-Fi connection already stored by NetworkManager does not need
to be recreated. Prepare every existing profile for automatic selection once:

```bash
sudo .venv/bin/python -m abr.wifi_profiles configure
```

This sets `connection.autoconnect=yes` and
`connection.autoconnect-retries=0`. At boot and after connection loss,
NetworkManager then keeps trying to use one of the stored networks that is
currently reachable.

## Checking Profile Name and SSID

Profile name and SSID are not necessarily identical. The ABR tool displays
profile names:

```bash
sudo .venv/bin/python -m abr.wifi_profiles list
```

NetworkManager displays the SSID of a specific profile:

```bash
nmcli -g 802-11-wireless.ssid connection show "Example WiFi"
```

Display every profile with its SSID:

```bash
nmcli -f NAME,TYPE,802-11-wireless.ssid connection show
```

For `switch`, copy the profile name from `abr.wifi_profiles list` exactly.
The UUID shown there can be used instead.

## Switching Manually

```bash
sudo .venv/bin/python -m abr.wifi_profiles switch Mobile
```

Alternatively, trigger automatic selection from all stored profiles
immediately:

```bash
sudo .venv/bin/python -m abr.wifi_profiles auto
```

Within a detected SSH session, `add`, `switch`, and `auto` are rejected by
default. Running them directly on the Pi with a keyboard and monitor is
safest. To deliberately sacrifice the current SSH connection, place the
override before the subcommand:

```bash
sudo .venv/bin/python -m abr.wifi_profiles --allow-ssh-disconnect switch Mobile
```

The ABR runtime continues independently of SSH as a systemd service.

If no keyboard or monitor is connected to the Pi, use this verified sequence:

1. Save the new profile over SSH using `add`; the active connection remains
   unchanged.
2. Verify the profile name and UUID with `list`.
3. Enable the target Wi-Fi network.
4. Deliberately switch with
   `--allow-ssh-disconnect switch PROFILE_NAME`.
5. Connect the other computer to the target network and reconnect to the Pi
   through `abr.local`, its IP address, or Raspberry Pi Connect.
6. To switch back, use the exact displayed name of the local profile.

If several networks are reachable at once, assign priorities while adding
them:

```bash
sudo .venv/bin/python -m abr.wifi_profiles add Home MyWiFi --priority 20
sudo .venv/bin/python -m abr.wifi_profiles add Mobile MyHotspot --priority 10
```

## Persistent Autoconnect Configuration

NetworkManager stores autoconnect properties directly in its connection
profiles and applies them at every boot. The installer sets these properties
once using the privileges already granted through `sudo`:

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
```

Verify:

```bash
sudo .venv/bin/python -m abr.wifi_profiles list
nmcli connection show
nmcli device status
```

The installer neither activates a connection nor switches Wi-Fi; it changes
only the persistent autoconnect properties of existing profiles. An earlier
version installed `abr-wifi-autoconnect.service`. That unit failed without
root privileges and would have been unnecessarily privileged if run as root.
The current installer disables and removes it during an update. Profiles
created later by external tools can be included by rerunning the installer or
`abr.wifi_profiles configure`.
