"use client";

import { useState } from "react";
import { RechargeForm } from "@/components/forms/RechargeForm";
import { usePaymentHistory } from "@/lib/api/payment";
import { formatPrice, formatDate } from "@/lib/utils/format";

const METHOD_LABELS: Record<string, string> = {
  alipay: "支付宝",
  wechat: "微信",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "处理中",
  success: "成功",
  failed: "失败",
  cancelled: "已取消",
};

const STATUS_STYLES: Record<string, string> = {
  success: "bg-green-100 text-green-700",
  pending: "bg-yellow-100 text-yellow-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-neutral-100 text-neutral-text-muted",
};

export default function RechargePage() {
  const [page, setPage] = useState(1);
  const [successToast, setSuccessToast] = useState("");

  const { data, isLoading } = usePaymentHistory(page);

  const handleSuccess = (amount: number) => {
    setSuccessToast(`充值成功 ${formatPrice(amount)}`);
    setPage(1);
    setTimeout(() => setSuccessToast(""), 5000);
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8">
      {/* Success Toast */}
      {successToast && (
        <div className="fixed top-20 right-4 z-50 px-4 py-3 bg-green-50 border border-green-200 rounded-md shadow-lg">
          <p className="text-sm text-green-700">{successToast}</p>
        </div>
      )}

      <div>
        <h1 className="text-2xl font-semibold mb-6">充值</h1>
        <RechargeForm onSuccess={handleSuccess} />
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-4">充值记录</h2>

        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-12 bg-neutral-bg rounded-md animate-pulse"
              />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="text-center py-12 text-neutral-text-muted">
            <p>还没有充值记录。选择金额开始充值。</p>
          </div>
        ) : (
          <>
            <div className="border border-neutral-border rounded-md overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-neutral-border bg-neutral-bg">
                    <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                      时间
                    </th>
                    <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                      金额
                    </th>
                    <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                      方式
                    </th>
                    <th className="text-left px-4 py-3 font-medium text-neutral-text-secondary">
                      状态
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-neutral-border last:border-0"
                    >
                      <td className="px-4 py-3 font-mono text-sm text-neutral-text-secondary">
                        {formatDate(item.createdAt)}
                      </td>
                      <td className="px-4 py-3 font-mono text-sm text-right">
                        {formatPrice(item.amount)}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {METHOD_LABELS[item.method] || item.method}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                            STATUS_STYLES[item.status] || "bg-neutral-100 text-neutral-text-muted"
                          }`}
                        >
                          {STATUS_LABELS[item.status] || item.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {data.total > data.pageSize && (
              <div className="flex items-center justify-between mt-4">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 text-sm rounded border border-neutral-border
                             hover:bg-neutral-bg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  上一页
                </button>
                <span className="text-sm text-neutral-text-secondary">
                  第 {page} 页，共 {Math.ceil(data.total / data.pageSize)} 页
                </span>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= Math.ceil(data.total / data.pageSize)}
                  className="px-3 py-1.5 text-sm rounded border border-neutral-border
                             hover:bg-neutral-bg disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  下一页
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
