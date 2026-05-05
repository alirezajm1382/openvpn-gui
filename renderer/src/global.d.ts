import type { OpenVpnApi } from '../../../shared/vpn';

declare global {
  interface Window {
    openVpn: OpenVpnApi;
  }
}

export {};
