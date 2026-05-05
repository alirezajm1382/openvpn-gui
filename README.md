# OpenVPN GUI

Electron desktop client for Debian-based distributions that imports OpenVPN
`.ovpn` profiles, starts and stops connections with OpenVPN 3 Linux when
available, and shows connection status, logs, and connectivity checks.

## Features

- Import `.ovpn` profiles from the Electron file picker.
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

## Development

Install Node dependencies, then run the Electron app:

```bash
yarn install
yarn dev
```

The Electron frontend talks to the existing Python OpenVPN backend through a
small JSON bridge. The legacy Python GTK frontend has been removed.

## Debian Package

Install the Debian packaging tools first:

```bash
sudo apt install dpkg fakeroot
```

Create the Electron Debian package with:

```bash
yarn make:deb
```

or:

```bash
./build-deb.sh
```

Forge writes release artifacts under `out/make`. The Electron package includes
the Python backend, the privileged helper, and a PolicyKit action installed by
the Debian post-install script. Installed launches go through a small wrapper
that forces the system GSettings schema cache, which avoids Snap-injected GNOME
schema mismatches such as missing `font-antialiasing`.

## Runtime Dependencies

The generated package depends on:

- `python3`
- `iputils-ping`
- `openvpn3-client` or `openvpn3` preferred, with `openvpn` as fallback
- `pkexec` and `polkitd` (`policykit-1` on older distributions) for OpenVPN 2 fallback

## Security Notes

OpenVPN 3 runs through the user's OpenVPN 3 D-Bus session. The OpenVPN 2
privileged helper validates that the selected config, credential, and secret key
files live inside the calling user's `~/.config/openvpn-gui/profiles` directory
before running OpenVPN as root. It also checks that a stopped process looks like
the matching OpenVPN profile before sending signals.
