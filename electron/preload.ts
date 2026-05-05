import { contextBridge, ipcRenderer } from 'electron';

import type { OpenVpnApi, StartProfileRequest } from '../shared/vpn';

const api: OpenVpnApi = {
  listProfiles: () => ipcRenderer.invoke('vpn:listProfiles'),
  importProfile: () => ipcRenderer.invoke('vpn:importProfile'),
  getStatus: (profileId: string) => ipcRenderer.invoke('vpn:getStatus', profileId),
  startProfile: (request: StartProfileRequest) => ipcRenderer.invoke('vpn:startProfile', request),
  stopProfile: (profileId: string) => ipcRenderer.invoke('vpn:stopProfile', profileId),
  deleteProfile: (profileId: string) => ipcRenderer.invoke('vpn:deleteProfile', profileId),
  runChecks: () => ipcRenderer.invoke('vpn:runChecks'),
};

contextBridge.exposeInMainWorld('openVpn', api);
