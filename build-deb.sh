#!/usr/bin/env bash
set -euo pipefail

APP_NAME="openvpn-gui"
VERSION="0.1.0"
ARCH="all"
PKG_DIR="build/${APP_NAME}_${VERSION}_${ARCH}"
DEB_PATH="dist/${APP_NAME}_${VERSION}_${ARCH}.deb"

rm -rf "${PKG_DIR}" dist
mkdir -p "${PKG_DIR}/DEBIAN"
mkdir -p "${PKG_DIR}/usr/bin"
mkdir -p "${PKG_DIR}/usr/lib/${APP_NAME}"
mkdir -p "${PKG_DIR}/usr/share/applications"
mkdir -p "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${PKG_DIR}/usr/share/polkit-1/actions"
mkdir -p dist

cp -a src/openvpn_gui "${PKG_DIR}/usr/lib/${APP_NAME}/"
find "${PKG_DIR}/usr/lib/${APP_NAME}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${PKG_DIR}/usr/lib/${APP_NAME}" -type f -name '*.py[co]' -delete
find "${PKG_DIR}/usr/lib/${APP_NAME}/openvpn_gui" -type f -exec chmod 0644 {} +
install -m 0755 scripts/openvpn-gui "${PKG_DIR}/usr/lib/${APP_NAME}/openvpn-gui"
install -m 0755 scripts/openvpn-gui-helper "${PKG_DIR}/usr/lib/${APP_NAME}/openvpn-gui-helper"
ln -s "../lib/${APP_NAME}/openvpn-gui" "${PKG_DIR}/usr/bin/openvpn-gui"

install -m 0644 data/openvpn-gui.desktop "${PKG_DIR}/usr/share/applications/openvpn-gui.desktop"
install -m 0644 data/com.openvpngui.helper.policy "${PKG_DIR}/usr/share/polkit-1/actions/com.openvpngui.helper.policy"
install -m 0644 data/icons/hicolor/scalable/apps/openvpn-gui.svg "${PKG_DIR}/usr/share/icons/hicolor/scalable/apps/openvpn-gui.svg"

cat > "${PKG_DIR}/DEBIAN/control" <<CONTROL
Package: ${APP_NAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Maintainer: OpenVPN GUI Maintainers <maintainers@example.invalid>
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, iputils-ping, openvpn3-client | openvpn3 | openvpn
Recommends: pkexec | policykit-1, polkitd | policykit-1, desktop-file-utils, hicolor-icon-theme
Description: GTK desktop client for OpenVPN profiles
 OpenVPN GUI imports .ovpn profiles, copies referenced certificate files,
 starts and stops OpenVPN through OpenVPN 3 Linux when available, and shows
 connection status and error details in a native Debian desktop interface.
CONTROL

cat > "${PKG_DIR}/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi

exit 0
POSTINST

cat > "${PKG_DIR}/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi

exit 0
POSTRM

chmod 0755 "${PKG_DIR}/DEBIAN/postinst" "${PKG_DIR}/DEBIAN/postrm"
find "${PKG_DIR}" -type d -exec chmod 0755 {} +

dpkg-deb --root-owner-group --build "${PKG_DIR}" "${DEB_PATH}"
echo "${DEB_PATH}"
