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
`connection.autoconnect-retries=1` so one broken profile does not monopolize
automatic activation. Install the recovery service below for continuous
retries across saved profiles; `configure` alone does not install it.

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

List profile names and types (query each SSID separately as above):

```bash
nmcli -f NAME,TYPE connection show
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

Within a detected SSH session, `switch`, `auto`, `watch`, and `add --activate`
are rejected by default. Plain `add` remains allowed. Install and check the
recovery service below before switching without a keyboard and monitor.
To allow the switch over SSH, place the override before the subcommand:

```bash
sudo .venv/bin/python -m abr.wifi_profiles --allow-ssh-disconnect switch Mobile
```

The ABR runtime continues independently of SSH as a systemd service.

If no keyboard or monitor is connected to the Pi, use this sequence with the recovery service installed:

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

## Continuous Recovery Service

Install once, including on devices using the previous configuration:

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
```

This configures profiles and installs/starts `abr-wifi-autoconnect.service`.
It runs as root to activate system profiles without an interactive permission
agent, starts at boot, and is independent of SSH and the reader service.

It checks `wlan0`, waiting ten seconds between iterations; scans and
activation attempts can extend each iteration. An established Wi-Fi connection is left
alone, including networks without Internet access. When disconnected, it
requests a scan and tries saved profiles in stable UUID order, cycling forever.
A failed profile does not prevent later profiles from being tried. NetworkManager's
own automatic selection still uses configured priorities. New/deleted profiles
are picked up automatically, and unknown open networks are never created.

Each activation command waits up to 45 seconds. Existing/manual activation
attempts get up to 120 seconds before recovery tries the next profile; an
nmcli timeout does not necessarily cancel activation inside NetworkManager.
Recovery resumes after failed manual switches and subsequent connection loss.
NetworkManager errors are retried, and systemd restarts the monitor if it exits.

An enabled, managed Wi-Fi adapter and a reachable saved network with valid
credentials are required. Missing/blocked adapters are checked repeatedly;
radio and management restrictions are not overridden. This checks the Wi-Fi
connection, not Internet availability.

```bash
sudo systemctl status abr-wifi-autoconnect.service --no-pager
sudo journalctl -u abr-wifi-autoconnect.service -n 30 -f
```

On-device validation: turn the hotspot off and back on, and verify reconnection
without SSH intervention. Also test a failing saved profile alongside a working
one. Automated tests simulate these cases; actual radio and DHCP behavior still
requires a Raspberry Pi test.

## Updating an Existing Installation

After transferring the updated code to the Pi, rerun the installer. A Git
update alone does not install/update the systemd unit. The installer restarts
the monitor, which preserves an established connection. The control-panel
service does not need to be stopped.

```bash
cd ~/src/abr
sudo deploy/install_wifi_autoconnect.sh
systemctl is-enabled abr-wifi-autoconnect.service
systemctl is-active abr-wifi-autoconnect.service
```

Expect `enabled` and `active`. `--allow-ssh-disconnect` neither installs a
service nor implements rollback; continued recovery requires the installed
monitor.

## Diagnostics

```bash
nmcli device status
nmcli radio wifi
sudo .venv/bin/python -m abr.wifi_profiles list
sudo journalctl -u abr-wifi-autoconnect.service -b -n 100 --no-pager
sudo journalctl -u NetworkManager.service -b -n 100 --no-pager
```

| Log / status | Meaning / next step |
|---|---|
| `Keine gespeicherten WLAN-Profile` | Save at least one profile using `add`. |
| `WLAN-Geraet nicht bereit` | Check the adapter, radio state and NetworkManager management. |
| `WLAN-Verbindung fehlgeschlagen` | Check SSID, password and range; other profiles will still be tried. |
| `WLAN verbunden` | Wi-Fi is connected. Lack of Internet alone does not trigger switching. |
| Service `inactive` / `failed` | Read the service log and rerun the installer. |

A full pass through several profiles can take several minutes. If no saved
network is reachable, the Pi remains offline and continues trying. To regain
SSH access, the Mac must be able to reach the connected network using
`abr.local` or the current IP address.

## Headless Device Test

1. Install the monitor and verify `enabled` / `active`.
2. Save two reachable networks with valid credentials.
3. Turn off the connected network; verify automatic connection to the other.
   Move the Mac to that network if necessary for SSH.
4. Turn off both networks, wait, then enable one again; verify reconnection
   even after multiple unsuccessful search rounds.
5. Repeat to verify recovery after subsequent connection loss.
6. Optionally activate a separate test profile with an incorrect password;
   a reachable valid profile must still be tried afterwards.
7. Reboot and verify automatic startup of the monitor and Wi-Fi connection.

As of 2026-09-17, 24 automated Wi-Fi tests pass. The new monitor has not yet
been validated on actual Raspberry Pi hardware.
