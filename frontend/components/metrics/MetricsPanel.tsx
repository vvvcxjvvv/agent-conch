'use client';

import { Coins, Hash, Layers, Shield, Cpu, Activity } from 'lucide-react';
import { useChatStore } from '@/lib/store';

export default function MetricsPanel() {
  const { metrics, guardrailEvents, status, toolCalls } = useChatStore();

  const guardrailBlocked = guardrailEvents.filter((e) => e.action === 'blocked').length;

  return (
    <div className="flex flex-col h-full border-l border-gray-200 bg-gray-50 p-4 space-y-4 overflow-y-auto">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">实时指标</h3>

      {/* 状态 */}
      <div className="flex items-center gap-2">
        <Activity className={`w-4 h-4 ${status === 'streaming' ? 'text-green-500 animate-pulse' : 'text-gray-400'}`} />
        <span className="text-sm text-gray-600">
          {status === 'streaming' ? '运行中' : status === 'done' ? '已完成' : status === 'error' ? '出错' : '空闲'}
        </span>
      </div>

      {/* Token */}
      <MetricCard
        icon={<Hash className="w-4 h-4 text-blue-500" />}
        label="Token"
        value={metrics.tokens.toLocaleString()}
      />

      {/* 成本 */}
      <MetricCard
        icon={<Coins className="w-4 h-4 text-green-500" />}
        label="成本"
        value={`$${metrics.cost.toFixed(4)}`}
      />

      {/* 步数 */}
      <MetricCard
        icon={<Layers className="w-4 h-4 text-purple-500" />}
        label="步数"
        value={String(metrics.steps)}
      />

      {/* 工具调用 */}
      <MetricCard
        icon={<Cpu className="w-4 h-4 text-orange-500" />}
        label="工具调用"
        value={String(toolCalls.length)}
      />

      {/* 护栏 */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Shield className="w-4 h-4 text-amber-500" />
          <span className="text-sm text-gray-600">护栏事件</span>
        </div>
        <div className="flex gap-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className={`flex-1 h-2 rounded-full ${
                i < guardrailBlocked ? 'bg-amber-400' : 'bg-gray-200'
              }`}
            />
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-1">
          拦截 {guardrailBlocked} 次 / {guardrailEvents.length} 事件
        </p>
      </div>

      {/* 模型信息 */}
      <div className="mt-auto pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-400">Profile: v2 MVP</p>
        <p className="text-xs text-gray-400">AgentConch v2.0</p>
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 p-2 bg-white border border-gray-100 rounded-md">
      {icon}
      <div className="flex-1">
        <p className="text-xs text-gray-400">{label}</p>
        <p className="text-sm font-medium text-gray-700">{value}</p>
      </div>
    </div>
  );
}
