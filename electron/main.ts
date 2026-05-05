import { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme } from 'electron';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { access } from 'node:fs/promises';

import type {
  ChecksResult,
  ImportProfileResult,
  OpenVpnApi,
  ProfilesResult,
  StartProfileRequest,
  StartProfileResult,
  StatusResult,
} from '../shared/vpn';

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

type BackendEnvelope<T> =
  | { ok: true; data: T }
  | { ok: false; error: { message?: string; traceback?: string } };

const PROFILE_ID_RE = /^[A-Za-z0-9._-]+$/;
const JSON_CONTENT_LIMIT = 1024 * 1024 * 2;

if (process.platform === 'linux') {
  app.commandLine.appendSwitch('disable-gpu');
  app.commandLine.appendSwitch('disable-software-rasterizer');
  app.commandLine.appendSwitch('disable-features', 'VaapiVideoDecoder,VaapiVideoEncoder');
  app.disableHardwareAcceleration();
}

process.on('uncaughtException', (error) => {
  console.error('[main] uncaught exception', error);
});

process.on('unhandledRejection', (reason) => {
  console.error('[main] unhandled rejection', reason);
});

function isProfileId(value: unknown): value is string {
  return typeof value === 'string' && PROFILE_ID_RE.test(value);
}

async function exists(candidate: string): Promise<boolean> {
  try {
    await access(candidate);
    return true;
  } catch {
    return false;
  }
}

async function resolveBackendRoot(): Promise<string> {
  if (app.isPackaged) {
    return process.resourcesPath;
  }

  const candidates = [
    process.cwd(),
    app.getAppPath(),
    path.resolve(__dirname, '..', '..'),
    path.resolve(__dirname, '..', '..', '..'),
  ];

  for (const candidate of candidates) {
    if (await exists(path.join(candidate, 'src', 'openvpn_gui', 'electron_bridge.py'))) {
      return candidate;
    }
  }

  return process.cwd();
}

function normalizeBackendError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }
  return new Error(String(error));
}

async function runBackend<T>(command: string, payload: Record<string, unknown> = {}): Promise<T> {
  const backendRoot = await resolveBackendRoot();
  const sourceRoot = path.join(backendRoot, 'src');
  const helperPath = path.join(backendRoot, 'scripts', 'openvpn-gui-helper');
  const python = process.env.OPENVPN_GUI_PYTHON || 'python3';

  return new Promise<T>((resolve, reject) => {
    const child = spawn(python, ['-m', 'openvpn_gui.electron_bridge', command], {
      cwd: backendRoot,
      env: {
        ...process.env,
        PYTHONPATH: [sourceRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
        OPENVPN_GUI_HELPER: process.env.OPENVPN_GUI_HELPER || helperPath,
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');

    child.stdout.on('data', (chunk: string) => {
      stdout += chunk;
      if (stdout.length > JSON_CONTENT_LIMIT) {
        child.kill();
        reject(new Error('Backend response was too large.'));
      }
    });

    child.stderr.on('data', (chunk: string) => {
      stderr += chunk;
    });

    child.on('error', (error) => {
      reject(normalizeBackendError(error));
    });

    child.on('close', () => {
      const trimmed = stdout.trim();
      if (!trimmed) {
        reject(new Error(stderr.trim() || 'Backend did not return a response.'));
        return;
      }

      try {
        const parsed = JSON.parse(trimmed) as BackendEnvelope<T>;
        if (parsed.ok) {
          resolve(parsed.data);
          return;
        }
        const message = parsed.error.message || stderr.trim() || 'Backend command failed.';
        reject(new Error(message));
      } catch (error) {
        reject(new Error(`Could not parse backend response: ${String(error)}\n${trimmed}`));
      }
    });

    child.stdin.end(JSON.stringify(payload));
  });
}

function requireProfileId(profileId: unknown): string {
  if (!isProfileId(profileId)) {
    throw new Error('Invalid profile id.');
  }
  return profileId;
}

function normalizeStartRequest(request: unknown): StartProfileRequest {
  if (!request || typeof request !== 'object') {
    throw new Error('Start request is required.');
  }

  const candidate = request as StartProfileRequest;
  const profileId = requireProfileId(candidate.profileId);
  const credentials = candidate.credentials;

  if (credentials !== undefined && (typeof credentials !== 'object' || credentials === null)) {
    throw new Error('Credentials must be an object.');
  }

  const text = (value: unknown): string | undefined => (typeof value === 'string' ? value : undefined);

  return {
    profileId,
    credentials: credentials
      ? {
          username: text(credentials.username),
          password: text(credentials.password),
          secret: text(credentials.secret),
          save: Boolean(credentials.save),
        }
      : undefined,
  };
}

function registerIpc(): void {
  const handlers: {
    [K in keyof OpenVpnApi]: (...args: Parameters<OpenVpnApi[K]>) => ReturnType<OpenVpnApi[K]>;
  } = {
    listProfiles: () => runBackend<ProfilesResult>('list-profiles'),
    importProfile: async () => {
      const result = await dialog.showOpenDialog({
        title: 'Import OpenVPN profile',
        properties: ['openFile'],
        filters: [{ name: 'OpenVPN profiles', extensions: ['ovpn'] }],
      });

      if (result.canceled || result.filePaths.length === 0) {
        return null;
      }

      const filePath = result.filePaths[0];
      if (!filePath) {
        return null;
      }

      return runBackend<ImportProfileResult>('import-profile', { path: filePath });
    },
    getStatus: (profileId) => runBackend<StatusResult>('status', { profileId: requireProfileId(profileId) }),
    startProfile: (request) => runBackend<StartProfileResult>('start', normalizeStartRequest(request)),
    stopProfile: async (profileId) => {
      await runBackend('stop', { profileId: requireProfileId(profileId) });
      return runBackend<StatusResult>('status', { profileId });
    },
    deleteProfile: (profileId) => runBackend<ProfilesResult>('delete', { profileId: requireProfileId(profileId) }),
    runChecks: () => runBackend<ChecksResult>('checks'),
  };

  ipcMain.handle('vpn:listProfiles', () => handlers.listProfiles());
  ipcMain.handle('vpn:importProfile', () => handlers.importProfile());
  ipcMain.handle('vpn:getStatus', (_event, profileId: string) => handlers.getStatus(profileId));
  ipcMain.handle('vpn:startProfile', (_event, request: StartProfileRequest) => handlers.startProfile(request));
  ipcMain.handle('vpn:stopProfile', (_event, profileId: string) => handlers.stopProfile(profileId));
  ipcMain.handle('vpn:deleteProfile', (_event, profileId: string) => handlers.deleteProfile(profileId));
  ipcMain.handle('vpn:runChecks', () => handlers.runChecks());
}

async function createWindow(): Promise<void> {
  nativeTheme.themeSource = 'system';
  Menu.setApplicationMenu(null);

  const window = new BrowserWindow({
    width: 1160,
    height: 740,
    minWidth: 940,
    minHeight: 620,
    title: 'OpenVPN GUI',
    backgroundColor: '#f6f7fb',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    await window.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    await window.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }
}

app.whenReady().then(() => {
  registerIpc();
  void createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
