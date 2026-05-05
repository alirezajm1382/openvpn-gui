import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FilePlus2,
  KeyRound,
  ListRestart,
  Loader2,
  Network,
  Plug,
  Power,
  RefreshCw,
  Shield,
  ShieldCheck,
  Signal,
  Trash2,
  WifiOff,
  X,
} from 'lucide-react';
import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';

import type { ConnectionStatus, ConnectivityCheck, CredentialsPayload, Profile } from '../../../shared/vpn';

type TabId = 'log' | 'checks';
type ForegroundAction = 'import' | 'connection' | 'delete' | null;
type StatusKind = 'connected' | 'connecting' | 'failed' | 'idle';
type ProfileStatusMap = Record<string, ConnectionStatus>;

interface CredentialModalState {
  missing: string[];
}

const DEFAULT_STATUS: ConnectionStatus = {
  running: false,
  pid: null,
  state: 'Disconnected',
  logTail: '',
};

function statusKind(status: ConnectionStatus | null): StatusKind {
  const label = (status?.state || '').toLowerCase();
  if (status?.running && label === 'connected') {
    return 'connected';
  }
  if (status?.running || label.includes('connecting')) {
    return 'connecting';
  }
  if (label.includes('failed') || label.includes('error') || label.includes('tls')) {
    return 'failed';
  }
  return 'idle';
}

function statusTone(status: ConnectionStatus | null): string {
  return statusKind(status);
}

function isConnectedStatus(status: ConnectionStatus | null | undefined): boolean {
  return Boolean(status?.running && status.state === 'Connected');
}

function shortPath(value: string | null | undefined): string {
  if (!value) {
    return 'Imported profile';
  }
  const parts = value.split('/').filter(Boolean);
  if (parts.length <= 3) {
    return value;
  }
  return `.../${parts.slice(-3).join('/')}`;
}

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return '--';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '--';
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function missingCredentialFields(profile: Profile): string[] {
  const missing: string[] = [];
  if (profile.needsCredentials && !profile.hasSavedAuth) {
    missing.push('username', 'password');
  }
  if (profile.needsSecret && !profile.hasSavedSecret) {
    missing.push('secret');
  }
  return missing;
}

function latencyWidth(check: ConnectivityCheck): string {
  if (!check.ok || check.latencyMs === null) {
    return '0%';
  }
  const score = Math.max(8, Math.min(100, 100 - check.latencyMs));
  return `${score}%`;
}

function ErrorBanner({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <AlertTriangle size={18} />
      <span>{message}</span>
      <button className="icon-button plain" type="button" title="Dismiss" onClick={onClose}>
        <X size={16} />
      </button>
    </div>
  );
}

function EmptyProfiles({ onImport, busy }: { onImport: () => void; busy: boolean }) {
  return (
    <div className="empty-profiles">
      <Shield size={34} />
      <strong>No profiles</strong>
      <button className="primary-button compact" type="button" onClick={onImport} disabled={busy}>
        <FilePlus2 size={16} />
        Import
      </button>
    </div>
  );
}

function ProfileSection({ title, count, connected, children }: { title: string; count: number; connected?: boolean; children: ReactNode }) {
  return (
    <section className={`profile-section ${connected ? 'connected' : ''}`}>
      <div className="profile-section-title">
        <span>{title}</span>
        <strong>{count}</strong>
      </div>
      {children}
    </section>
  );
}

function ProfileButton({
  profile,
  selected,
  status,
  onSelect,
}: {
  profile: Profile;
  selected: boolean;
  status?: ConnectionStatus;
  onSelect: () => void;
}) {
  const kind = statusKind(status || null);

  return (
    <button className={`profile-button ${selected ? 'selected' : ''}`} type="button" onClick={onSelect}>
      <span className="profile-mark">
        {status?.running ? <ShieldCheck size={24} className={`status-icon ${kind}`} /> : <Shield size={24} className={`status-icon ${kind}`} />}
      </span>
      <span className="profile-copy">
        <span className="profile-name">{profile.name}</span>
        <span className="profile-path">{shortPath(profile.configPath)}</span>
      </span>
      <span className="profile-side">
        {status?.running && <span className={`profile-live-dot ${kind}`} title={status.state} />}
        {(profile.hasSavedAuth || profile.hasSavedSecret) && <KeyRound className="saved-key" size={14} />}
      </span>
    </button>
  );
}

function StatusRing({ status }: { status: ConnectionStatus | null }) {
  const kind = statusKind(status);
  return (
    <div className={`status-ring ${kind}`} aria-label={status?.state || 'Disconnected'}>
      <div className="status-ring-inner">
        {kind === 'connected' && <CheckCircle2 size={34} />}
        {kind === 'connecting' && <Loader2 className="spin" size={34} />}
        {kind === 'failed' && <AlertTriangle size={34} />}
        {kind === 'idle' && <Power size={34} />}
      </div>
    </div>
  );
}

function StatusTimeline({ status }: { status: ConnectionStatus | null }) {
  const kind = statusKind(status);
  const steps = [
    { id: 'ready', label: 'Ready', active: true },
    { id: 'auth', label: 'Auth', active: kind !== 'idle' },
    { id: 'link', label: 'Link', active: kind === 'connecting' || kind === 'connected' },
    { id: 'secure', label: 'Secure', active: kind === 'connected' },
  ];

  return (
    <div className="timeline" aria-label="Connection state">
      {steps.map((step) => (
        <span className={`timeline-step ${step.active ? 'active' : ''}`} key={step.id}>
          <span />
          {step.label}
        </span>
      ))}
    </div>
  );
}

function ChecksView({ checks, busy, onRefresh }: { checks: ConnectivityCheck[]; busy: boolean; onRefresh: () => void }) {
  return (
    <section className="tool-section">
      <div className="section-heading">
        <div>
          <h2>Checks</h2>
          <p>{checks.length ? `${checks.filter((check) => check.ok).length}/${checks.length} online` : 'Paused'}</p>
        </div>
        <button className="icon-button" type="button" title="Refresh checks" onClick={onRefresh} disabled={busy}>
          {busy ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
        </button>
      </div>

      <div className="check-list">
        {checks.length === 0 && (
          <div className="muted-state">
            <WifiOff size={22} />
            <span>No check results</span>
          </div>
        )}
        {checks.map((check) => (
          <div className="check-row" key={check.target}>
            <div className="check-target">
              <span className={`check-dot ${check.ok ? 'ok' : 'fail'}`} />
              <span>{check.target}</span>
            </div>
            <div className="latency-meter" title={check.message}>
              <span style={{ width: latencyWidth(check) }} />
            </div>
            <span className="check-latency">{check.latencyMs === null ? '--' : `${check.latencyMs.toFixed(1)} ms`}</span>
            <span className={`check-state ${check.ok ? 'ok' : 'fail'}`}>{check.ok ? 'Online' : 'Failed'}</span>
            <span className="check-time">{formatTime(check.checkedAt)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function LogView({ status }: { status: ConnectionStatus | null }) {
  return (
    <section className="tool-section">
      <div className="section-heading">
        <div>
          <h2>Log</h2>
          <p>{status?.pid ? `PID ${status.pid}` : 'Runtime output'}</p>
        </div>
      </div>
      <pre className="log-view">{status?.logTail?.trim() || 'No log output yet.'}</pre>
    </section>
  );
}

function CredentialsModal({
  profile,
  missing,
  busy,
  onCancel,
  onSubmit,
}: {
  profile: Profile;
  missing: string[];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (credentials: CredentialsPayload) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [secret, setSecret] = useState('');
  const [save, setSave] = useState(profile.hasSavedAuth || profile.hasSavedSecret);
  const needsUserPass = missing.includes('username') || profile.needsCredentials;
  const needsSecret = missing.includes('secret') || profile.needsSecret;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit({ username, password, secret, save });
  }

  return (
    <div className="modal-backdrop">
      <form className="modal" onSubmit={handleSubmit}>
        <div className="modal-title">
          <KeyRound size={21} />
          <div>
            <h2>{profile.name}</h2>
            <p>Credentials</p>
          </div>
        </div>

        {needsUserPass && (
          <div className="field-grid">
            <label>
              <span>Username</span>
              <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
            </label>
            <label>
              <span>Password</span>
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
              />
            </label>
          </div>
        )}

        {needsSecret && (
          <label className="field">
            <span>Secret key</span>
            <input
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              type="password"
              autoComplete="off"
            />
          </label>
        )}

        <label className="checkbox-row">
          <input checked={save} onChange={(event) => setSave(event.target.checked)} type="checkbox" />
          <span>Remember for this profile</span>
        </label>

        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? <Loader2 className="spin" size={17} /> : <Plug size={17} />}
            Connect
          </button>
        </div>
      </form>
    </div>
  );
}

export function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [profileStatuses, setProfileStatuses] = useState<ProfileStatusMap>({});
  const [checks, setChecks] = useState<ConnectivityCheck[]>([]);
  const [tab, setTab] = useState<TabId>('log');
  const [foregroundAction, setForegroundAction] = useState<ForegroundAction>(null);
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [credentialsModal, setCredentialsModal] = useState<CredentialModalState | null>(null);

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedId) || null,
    [profiles, selectedId],
  );
  const currentStatus = (selectedId ? profileStatuses[selectedId] : null) || status || DEFAULT_STATUS;
  const connected = currentStatus.running && currentStatus.state === 'Connected';
  const firstCheck = checks[0] || null;
  const importing = foregroundAction === 'import';
  const connecting = foregroundAction === 'connection';
  const deleting = foregroundAction === 'delete';
  const connectedProfiles = useMemo(
    () => profiles.filter((profile) => isConnectedStatus(profileStatuses[profile.id])),
    [profiles, profileStatuses],
  );
  const otherProfiles = useMemo(
    () => profiles.filter((profile) => !isConnectedStatus(profileStatuses[profile.id])),
    [profiles, profileStatuses],
  );

  const refreshAllStatuses = useCallback(async (nextProfiles: Profile[], activeProfileId: string | null) => {
    if (nextProfiles.length === 0) {
      setProfileStatuses({});
      return;
    }

    const entries = await Promise.all(
      nextProfiles.map(async (profile) => {
        try {
          const result = await window.openVpn.getStatus(profile.id);
          return [profile.id, result.status] as const;
        } catch {
          return null;
        }
      }),
    );

    setProfileStatuses((current) => {
      const next: ProfileStatusMap = {};
      for (const profile of nextProfiles) {
        if (current[profile.id]) {
          next[profile.id] = current[profile.id];
        }
      }
      for (const entry of entries) {
        if (entry) {
          next[entry[0]] = entry[1];
        }
      }
      return next;
    });

    const selectedEntry = entries.find((entry) => entry?.[0] === activeProfileId);
    if (selectedEntry) {
      setStatus(selectedEntry[1]);
    }
  }, []);

  const loadProfiles = useCallback(async () => {
    setLoadingProfiles(true);
    try {
      const result = await window.openVpn.listProfiles();
      setProfiles(result.profiles);
      setSelectedId((current) => current || result.profiles[0]?.id || null);
      void refreshAllStatuses(result.profiles, null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoadingProfiles(false);
    }
  }, [refreshAllStatuses]);

  const refreshStatus = useCallback(
    async (profileId = selectedId) => {
      if (!profileId) {
        setStatus(null);
        return;
      }
      try {
        const result = await window.openVpn.getStatus(profileId);
        setStatus(result.status);
        setProfileStatuses((current) => ({ ...current, [profileId]: result.status }));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [selectedId],
  );

  const refreshChecks = useCallback(async (showSpinner = false) => {
    if (!connected) {
      setChecks([]);
      setChecking(false);
      return;
    }
    if (showSpinner) {
      setChecking(true);
    }
    try {
      const result = await window.openVpn.runChecks();
      setChecks(result.checks);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (showSpinner) {
        setChecking(false);
      }
    }
  }, [connected]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    void refreshStatus();
    const timer = window.setInterval(() => {
      void refreshStatus();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  useEffect(() => {
    void refreshAllStatuses(profiles, selectedId);
    const timer = window.setInterval(() => {
      void refreshAllStatuses(profiles, selectedId);
    }, 7000);
    return () => window.clearInterval(timer);
  }, [profiles, refreshAllStatuses, selectedId]);

  useEffect(() => {
    if (!connected) {
      setChecks([]);
      return;
    }
    void refreshChecks();
    const timer = window.setInterval(() => {
      void refreshChecks();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [connected, refreshChecks]);

  async function handleImport() {
    setForegroundAction('import');
    setError(null);
    try {
      const result = await window.openVpn.importProfile();
      if (result) {
        setProfiles(result.profiles);
        setSelectedId(result.profile.id);
        await refreshStatus(result.profile.id);
        void refreshAllStatuses(result.profiles, result.profile.id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setForegroundAction(null);
    }
  }

  async function handleConnect() {
    if (!selectedProfile) {
      return;
    }

    setError(null);
    if (currentStatus.running) {
      setForegroundAction('connection');
      try {
        const result = await window.openVpn.stopProfile(selectedProfile.id);
        setStatus(result.status);
        setProfileStatuses((current) => ({ ...current, [selectedProfile.id]: result.status }));
        setChecks([]);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setForegroundAction(null);
      }
      return;
    }

    const missing = missingCredentialFields(selectedProfile);
    if (missing.length > 0) {
      setCredentialsModal({ missing });
      return;
    }

    setForegroundAction('connection');
    try {
      const result = await window.openVpn.startProfile({ profileId: selectedProfile.id });
      if (result.needsCredentials) {
        setCredentialsModal({ missing: result.missing || [] });
        return;
      }
      const refreshedProfile = result.profile;
      if (refreshedProfile) {
        setProfiles((current) =>
          current.map((profile) => (profile.id === refreshedProfile.id ? refreshedProfile : profile)),
        );
      }
      setStatus(result.status || DEFAULT_STATUS);
      if (result.status) {
        setProfileStatuses((current) => ({ ...current, [selectedProfile.id]: result.status || DEFAULT_STATUS }));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setForegroundAction(null);
    }
  }

  async function handleCredentialSubmit(credentials: CredentialsPayload) {
    if (!selectedProfile) {
      return;
    }

    setForegroundAction('connection');
    setError(null);
    try {
      const result = await window.openVpn.startProfile({ profileId: selectedProfile.id, credentials });
      if (result.needsCredentials) {
        setCredentialsModal({ missing: result.missing || [] });
        setError('Credentials are required for this profile.');
        return;
      }
      const refreshedProfile = result.profile;
      if (refreshedProfile) {
        setProfiles((current) =>
          current.map((profile) => (profile.id === refreshedProfile.id ? refreshedProfile : profile)),
        );
      }
      setStatus(result.status || DEFAULT_STATUS);
      if (result.status) {
        setProfileStatuses((current) => ({ ...current, [selectedProfile.id]: result.status || DEFAULT_STATUS }));
      }
      setCredentialsModal(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setForegroundAction(null);
    }
  }

  async function handleDelete() {
    if (!selectedProfile) {
      return;
    }
    if (!window.confirm(`Delete ${selectedProfile.name}?`)) {
      return;
    }

    setForegroundAction('delete');
    setError(null);
    try {
      const result = await window.openVpn.deleteProfile(selectedProfile.id);
      setProfiles(result.profiles);
      setSelectedId(result.profiles[0]?.id || null);
      setStatus(null);
      setProfileStatuses((current) => {
        const next: ProfileStatusMap = {};
        for (const profile of result.profiles) {
          if (current[profile.id]) {
            next[profile.id] = current[profile.id];
          }
        }
        return next;
      });
      setChecks([]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setForegroundAction(null);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <span className="brand-mark">
            <Network size={24} />
          </span>
          <div>
            <h1>OpenVPN GUI</h1>
            <p>Profile manager</p>
          </div>
        </div>

        <div className="sidebar-actions">
          <button className="primary-button" type="button" onClick={handleImport} disabled={importing}>
            {importing ? <Loader2 className="spin" size={17} /> : <FilePlus2 size={17} />}
            Import
          </button>
          <button
            className="icon-button"
            type="button"
            title="Reload profiles"
            onClick={loadProfiles}
            disabled={loadingProfiles}
          >
            {loadingProfiles ? <Loader2 className="spin" size={18} /> : <ListRestart size={18} />}
          </button>
        </div>

        <div className="profile-list">
          {profiles.length === 0 && <EmptyProfiles onImport={handleImport} busy={importing} />}
          {connectedProfiles.length > 0 && (
            <ProfileSection title="Connected" count={connectedProfiles.length} connected>
              {connectedProfiles.map((profile) => (
                <ProfileButton
                  key={profile.id}
                  profile={profile}
                  status={profileStatuses[profile.id]}
                  selected={profile.id === selectedId}
                  onSelect={() => {
                    setSelectedId(profile.id);
                    setTab('log');
                  }}
                />
              ))}
            </ProfileSection>
          )}
          {otherProfiles.length > 0 && (
            <ProfileSection title="Profiles" count={otherProfiles.length}>
              {otherProfiles.map((profile) => (
                <ProfileButton
                  key={profile.id}
                  profile={profile}
                  status={profileStatuses[profile.id]}
                  selected={profile.id === selectedId}
                  onSelect={() => {
                    setSelectedId(profile.id);
                    setTab('log');
                  }}
                />
              ))}
            </ProfileSection>
          )}
        </div>
      </aside>

      <section className="workspace">
        {error && <ErrorBanner message={error} onClose={() => setError(null)} />}

        <header className="profile-header">
          <div className="profile-heading">
            <span className={`state-pill ${statusTone(currentStatus)}`}>
              <Activity size={14} />
              {selectedProfile ? currentStatus.state : 'No profile'}
            </span>
            <h2>{selectedProfile?.name || 'No profile selected'}</h2>
            <p>{selectedProfile ? shortPath(selectedProfile.configPath) : 'Import an .ovpn file'}</p>
          </div>

          <div className="header-actions">
            <button
              className="icon-button danger"
              type="button"
              title="Delete profile"
              onClick={handleDelete}
              disabled={!selectedProfile || deleting || currentStatus.running}
            >
              {deleting ? <Loader2 className="spin" size={18} /> : <Trash2 size={18} />}
            </button>
            <button
              className={`connect-button ${connected ? 'disconnect' : ''}`}
              type="button"
              onClick={handleConnect}
              disabled={!selectedProfile || connecting}
            >
              {connecting ? <Loader2 className="spin" size={18} /> : <Power size={18} />}
              {currentStatus.running ? 'Disconnect' : 'Connect'}
            </button>
          </div>
        </header>

        <div className="status-layout">
          <section className="connection-panel">
            <StatusRing status={currentStatus} />
            <div className="connection-copy">
              <span className="eyebrow">ovpn Profile</span>
              <h2>{currentStatus.state}</h2>
              <p>{selectedProfile?.sourcePath ? shortPath(selectedProfile.sourcePath) : selectedProfile?.configPath || 'Ready'}</p>
              <StatusTimeline status={currentStatus} />
            </div>
          </section>

          <section className="signal-panel">
            <div className="signal-row">
              <Signal size={19} />
              <span>Checks</span>
              <strong>{checks.length ? `${checks.filter((check) => check.ok).length}/${checks.length}` : '--'}</strong>
            </div>
            <div className="signal-row">
              <Clock3 size={19} />
              <span>Last update</span>
              <strong>{firstCheck ? formatTime(firstCheck.checkedAt) : '--'}</strong>
            </div>
          </section>
        </div>

        <nav className="tabs" aria-label="Profile details">
          <button className={tab === 'log' ? 'active' : ''} type="button" onClick={() => setTab('log')}>
            Log
          </button>
          <button className={tab === 'checks' ? 'active' : ''} type="button" onClick={() => setTab('checks')}>
            Checks
          </button>
        </nav>

        {tab === 'log' ? (
          <LogView status={currentStatus} />
        ) : (
          <ChecksView checks={checks} busy={checking} onRefresh={() => refreshChecks(true)} />
        )}
      </section>

      {credentialsModal && selectedProfile && (
        <CredentialsModal
          profile={selectedProfile}
          missing={credentialsModal.missing}
          busy={connecting}
          onCancel={() => setCredentialsModal(null)}
          onSubmit={handleCredentialSubmit}
        />
      )}
    </main>
  );
}
