const API_BASE = '/api';

export interface Session {
  id: string;
  profile: string;
  title: string;
  created_at: string;
  messages: Array<{ id: string; role: string; content: string }>;
}

export interface ProfileInfo {
  name: string;
  file: string;
}

export interface ProfileDetail {
  name: string;
  description: string;
  model: string;
  model_fallback: string | null;
  max_steps: number;
  max_tokens: number | null;
  domains: Record<string, { impl: string; params: Record<string, unknown> }>;
}

export async function createSession(profile: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/chat/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile }),
  });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function listSessions(): Promise<Session[]> {
  const res = await fetch(`${API_BASE}/chat/sessions`);
  if (!res.ok) throw new Error('Failed to list sessions');
  const data = await res.json();
  return data;
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${API_BASE}/chat/sessions/${id}`, { method: 'DELETE' });
}

export async function listProfiles(): Promise<ProfileInfo[]> {
  const res = await fetch(`${API_BASE}/profiles`);
  if (!res.ok) throw new Error('Failed to list profiles');
  const data = await res.json();
  return data.profiles;
}

export async function getProfile(name: string): Promise<ProfileDetail> {
  const res = await fetch(`${API_BASE}/profiles/${name}`);
  if (!res.ok) throw new Error('Failed to get profile');
  return res.json();
}

export async function listPlugins(): Promise<Record<string, string[]>> {
  const res = await fetch(`${API_BASE}/plugins`);
  if (!res.ok) throw new Error('Failed to list plugins');
  const data = await res.json();
  return data.plugins;
}
