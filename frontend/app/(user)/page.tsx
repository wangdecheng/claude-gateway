"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/AuthContext";
import { useUsageStats } from "@/lib/api/usage";
import { formatPrice, formatNumber } from "@/lib/utils/format";

export default function DashboardPage() {
  const { user } = useAuth();
  const { data: stats, isLoading } = useUsageStats();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">
        {user ? `欢迎，${user.email}` : "Dashboard"}
      </h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>sk 数量</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {isLoading ? "—" : stats?.activeKeys ?? 0}
            </p>
            <p className="mt-1 text-sm text-neutral-text-secondary">
              {stats && stats.activeKeys > 0
                ? `已创建 ${stats.activeKeys} 个活跃密钥`
                : "还没有创建 sk"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>今日调用</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {isLoading ? "—" : formatNumber(stats?.todayCalls ?? 0)}
            </p>
            <p className="mt-1 text-sm text-neutral-text-secondary">
              {stats && stats.todayCalls > 0
                ? `今日 ${stats.todayCalls} 次 API 调用`
                : "无 API 调用记录"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>今日费用</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-bold">
              {isLoading ? "—" : formatPrice(stats?.todayCostCents ?? 0)}
            </p>
            <p className="mt-1 text-sm text-neutral-text-secondary">
              {stats && stats.todayCostCents > 0
                ? `今日消耗 ${formatPrice(stats.todayCostCents)}`
                : "今天免费"}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
