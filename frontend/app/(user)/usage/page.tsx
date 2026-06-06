"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useUsageStats, useUsageHistory } from "@/lib/api/usage";
import { formatPrice, formatNumber, formatTokens, formatDate } from "@/lib/utils/format";

const DAY_OPTIONS = [
  { label: "7 天", value: 7 },
  { label: "30 天", value: 30 },
  { label: "90 天", value: 90 },
];

export default function UsagePage() {
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(1);
  const { data: stats, isLoading: statsLoading } = useUsageStats(days);
  const { data: history, isLoading: historyLoading } = useUsageHistory(page);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">用量统计</h1>

      {/* Stats Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-neutral-text-secondary">
              今日调用
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {statsLoading ? "—" : formatNumber(stats?.todayCalls ?? 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-neutral-text-secondary">
              今日 Tokens
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {statsLoading ? "—" : formatTokens(stats?.todayTokens ?? 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-neutral-text-secondary">
              今日费用
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {statsLoading ? "—" : formatPrice(stats?.todayCostCents ?? 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-neutral-text-secondary">
              活跃 sk
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {statsLoading ? "—" : stats?.activeKeys ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Daily Breakdown */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>每日用量</CardTitle>
          <div className="flex gap-2">
            {DAY_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                variant={days === opt.value ? "primary" : "secondary"}
                size="sm"
                onClick={() => setDays(opt.value)}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {statsLoading ? (
            <p className="text-sm text-neutral-text-secondary">加载中...</p>
          ) : stats && stats.daily.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-neutral-border text-left text-neutral-text-secondary">
                    <th className="py-2 font-medium">日期</th>
                    <th className="py-2 font-medium text-right">调用次数</th>
                    <th className="py-2 font-medium text-right">Tokens</th>
                    <th className="py-2 font-medium text-right">费用</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.daily.map((d) => (
                    <tr
                      key={d.date}
                      className="border-b border-neutral-border last:border-0"
                    >
                      <td className="py-2 text-neutral-text-primary">{d.date}</td>
                      <td className="py-2 text-right font-mono">
                        {formatNumber(d.calls)}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatTokens(d.tokens)}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {formatPrice(d.costCents)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-neutral-text-secondary">暂无用量数据</p>
          )}
        </CardContent>
      </Card>

      {/* Call History */}
      <Card>
        <CardHeader>
          <CardTitle>调用记录</CardTitle>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <p className="text-sm text-neutral-text-secondary">加载中...</p>
          ) : history && history.records.length > 0 ? (
            <div className="space-y-3">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-border text-left text-neutral-text-secondary">
                      <th className="py-2 font-medium">时间</th>
                      <th className="py-2 font-medium">模型</th>
                      <th className="py-2 font-medium text-right">请求</th>
                      <th className="py-2 font-medium text-right">响应</th>
                      <th className="py-2 font-medium text-right">总计</th>
                      <th className="py-2 font-medium text-right">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.records.map((r) => (
                      <tr
                        key={r.id}
                        className="border-b border-neutral-border last:border-0"
                      >
                        <td className="py-2 text-neutral-text-primary">
                          {formatDate(r.createdAt)}
                        </td>
                        <td className="py-2 font-mono text-xs">{r.model}</td>
                        <td className="py-2 text-right font-mono">
                          {formatTokens(r.requestTokens)}
                        </td>
                        <td className="py-2 text-right font-mono">
                          {formatTokens(r.responseTokens)}
                        </td>
                        <td className="py-2 text-right font-mono">
                          {formatTokens(r.totalTokens)}
                        </td>
                        <td className="py-2 text-right font-mono">
                          {formatPrice(r.costCents)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {history.total > history.pageSize && (
                <div className="flex items-center justify-between pt-2">
                  <p className="text-sm text-neutral-text-secondary">
                    共 {history.total} 条记录
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      上一页
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={page * history.pageSize >= history.total}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-neutral-text-secondary">暂无调用记录</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
