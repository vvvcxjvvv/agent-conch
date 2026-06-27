'use client';

import { useState, useEffect } from 'react';
import { MessageSquare, Plus, Trash2, ChevronDown } from 'lucide-react';
import { Session, ProfileInfo, listSessions, createSession, deleteSession, listProfiles } from '@/lib/api';

interface SidebarProps {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  selectedProfile: string;
  onSelectProfile: (name: string) => void;
}

export default function Sidebar({
  currentSessionId,
  onSelectSession,
  selectedProfile,
  onSelectProfile,
}: SidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [profileOpen, setProfileOpen] = useState(false);

  useEffect(() => {
    refreshSessions();
    listProfiles().then(setProfiles).catch(console.error);
  }, []);

  const refreshSessions = async () => {
    try {
      const list = await listSessions();
      setSessions(list);
    } catch (e) {
      console.error(e);
    }
  };

  const handleNew = async () => {
    try {
      const s = await createSession(selectedProfile);
      setSessions((prev) => [s, ...prev]);
      onSelectSession(s.id);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (currentSessionId === id) onSelectSession(null);
  };

  return (
    <div className="flex flex-col h-full border-r border-gray-200 bg-gray-50">
      {/* Profile 选择器 */}
      <div className="p-3 border-b border-gray-200">
        <button
          onClick={() => setProfileOpen(!profileOpen)}
          className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium bg-white border border-gray-200 rounded-md hover:bg-gray-50"
        >
          <span>{selectedProfile}</span>
          <ChevronDown className="w-4 h-4" />
        </button>
        {profileOpen && (
          <div className="mt-1 bg-white border border-gray-200 rounded-md shadow-sm max-h-48 overflow-y-auto">
            {profiles.map((p) => (
              <button
                key={p.name}
                onClick={() => {
                  onSelectProfile(p.name);
                  setProfileOpen(false);
                }}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 ${
                  selectedProfile === p.name ? 'bg-blue-50 text-blue-600' : ''
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 新建会话 */}
      <div className="p-3">
        <button
          onClick={handleNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" />
          新建会话
        </button>
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 ? (
          <p className="text-xs text-gray-400 text-center mt-8">暂无会话</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer mb-1 ${
                currentSessionId === s.id
                  ? 'bg-blue-100 text-blue-700'
                  : 'hover:bg-gray-100'
              }`}
              onClick={() => onSelectSession(s.id)}
            >
              <MessageSquare className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 truncate text-sm">{s.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(s.id);
                }}
                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
