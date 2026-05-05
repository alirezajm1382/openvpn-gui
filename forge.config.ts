import type { ForgeConfig } from '@electron-forge/shared-types';
import { MakerDeb } from '@electron-forge/maker-deb';
import { MakerZIP } from '@electron-forge/maker-zip';
import { VitePlugin } from '@electron-forge/plugin-vite';
import path from 'node:path';

const config: ForgeConfig = {
  packagerConfig: {
    executableName: 'openvpn-gui',
    icon: path.resolve(__dirname, 'data/icons/hicolor/scalable/apps/openvpn-gui'),
    asar: true,
    extraResource: [
      path.resolve(__dirname, 'src'),
      path.resolve(__dirname, 'scripts'),
      path.resolve(__dirname, 'packaging/electron'),
    ],
  },
  rebuildConfig: {},
  makers: [
    new MakerDeb({
      options: {
        name: 'openvpn-gui',
        productName: 'OpenVPN GUI',
        genericName: 'OpenVPN profile manager',
        section: 'net',
        priority: 'optional',
        maintainer: 'OpenVPN GUI Maintainers <maintainers@example.invalid>',
        bin: 'resources/electron/openvpn-gui',
        icon: path.resolve(__dirname, 'data/icons/hicolor/scalable/apps/openvpn-gui.svg'),
        categories: ['Network', 'Security'],
        depends: [
          'python3 (>= 3.8)',
          'iputils-ping',
          'openvpn3-client | openvpn3 | openvpn',
          'pkexec | policykit-1',
          'polkitd | policykit-1',
        ],
        scripts: {
          postinst: path.resolve(__dirname, 'packaging/electron/postinst'),
          postrm: path.resolve(__dirname, 'packaging/electron/postrm'),
        },
      },
    }),
    new MakerZIP({}, ['linux']),
  ],
  plugins: [
    new VitePlugin({
      build: [
        {
          entry: 'electron/main.ts',
          config: 'vite.main.config.ts',
        },
        {
          entry: 'electron/preload.ts',
          config: 'vite.preload.config.ts',
        },
      ],
      renderer: [
        {
          name: 'main_window',
          config: 'vite.renderer.config.ts',
        },
      ],
    }),
  ],
};

export default config;
