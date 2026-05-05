export interface Profile {
  id: string;
  name: string;
  configPath: string;
  sourcePath: string | null;
  importedAt: string;
  needsCredentials: boolean;
  needsSecret: boolean;
  hasSavedAuth: boolean;
  hasSavedSecret: boolean;
}

export interface ConnectionStatus {
  running: boolean;
  pid: number | null;
  state: string;
  logTail: string;
}

export interface ConnectivityCheck {
  target: string;
  ok: boolean;
  latencyMs: number | null;
  checkedAt: string;
  message: string;
}

export interface CredentialsPayload {
  username?: string;
  password?: string;
  secret?: string;
  save?: boolean;
}

export interface StartProfileRequest {
  profileId: string;
  credentials?: CredentialsPayload;
}

export interface StartProfileResult {
  message?: string;
  profile?: Profile;
  status?: ConnectionStatus;
  needsCredentials?: boolean;
  missing?: string[];
}

export interface ProfilesResult {
  profiles: Profile[];
}

export interface ImportProfileResult extends ProfilesResult {
  profile: Profile;
}

export interface StatusResult {
  status: ConnectionStatus;
}

export interface ChecksResult {
  checks: ConnectivityCheck[];
}

export interface OpenVpnApi {
  listProfiles: () => Promise<ProfilesResult>;
  importProfile: () => Promise<ImportProfileResult | null>;
  getStatus: (profileId: string) => Promise<StatusResult>;
  startProfile: (request: StartProfileRequest) => Promise<StartProfileResult>;
  stopProfile: (profileId: string) => Promise<StatusResult>;
  deleteProfile: (profileId: string) => Promise<ProfilesResult>;
  runChecks: () => Promise<ChecksResult>;
}
