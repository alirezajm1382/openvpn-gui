# OpenVPN GUI

A small GTK desktop client for Debian-based distributions that imports OpenVPN
`.ovpn` profiles, starts and stops connections with OpenVPN 3 Linux when
available, and shows connection status and logs.

## Features

- Import `.ovpn` profiles from the file picker.
- Copy referenced files such as `ca`, `cert`, `key`, `tls-auth`, `tls-crypt`,
  and `auth-user-pass` into a private per-profile folder.
- Prompt for username/password when a profile uses bare `auth-user-pass`.
- Prompt for a per-profile secret key/private-key passphrase and optionally
  remember it for that profile.
- Prefer OpenVPN 3 Linux (`openvpn3`) for session start/stop and status.
- Fall back to OpenVPN 2 with `pkexec` using the packaged privileged helper.
- Show command output, exit code, stderr, and log tails when startup fails.
- Ping development endpoints such as Vercel, Google, GitHub, GitHub API, and
  npm registry while the selected VPN profile is connected.
- Keep profile data under `~/.config/openvpn-gui`.
- Keep runtime status, PID, and log files under `/run/user/$UID/openvpn-gui`.

## Build

```bash
./build-deb.sh
```

The package is written to:

```text
dist/openvpn-gui_0.1.0_all.deb
```

Install it with:

```bash
sudo apt install ./dist/openvpn-gui_0.1.0_all.deb
```

## Run From Source

The GUI can be launched without installing the package:

```bash
PYTHONPATH=src ./scripts/openvpn-gui
```

Starting or stopping a VPN connection from source uses `openvpn3` when it is
installed. The OpenVPN 2 fallback requires installing the PolicyKit policy from
the Debian package, because `pkexec` only authorizes installed actions.

## Package Dependencies

The generated package depends on:

- `python3`
- `python3-gi`
- `gir1.2-gtk-3.0`
- `iputils-ping`
- `openvpn3-client` or `openvpn3` preferred, with `openvpn` as fallback
- `pkexec` and `polkitd` (`policykit-1` on older distributions) for OpenVPN 2 fallback

## Security Notes

OpenVPN 3 runs through the user's OpenVPN 3 D-Bus session. The OpenVPN 2
privileged helper validates that the selected config, credential, and secret key
files live inside the calling user's `~/.config/openvpn-gui/profiles` directory
before running OpenVPN as root. It also checks that a stopped process looks like
the matching OpenVPN profile before sending signals.
