"use client";

import { useState } from "react";
import { KeyList } from "@/components/data/KeyList";
import { CreateKeyForm } from "@/components/forms/CreateKeyForm";
import { useBaseUrl } from "@/lib/api/keys";
import { Button } from "@/components/ui/button";
import { InlineToast, type InlineToastVariant } from "@/components/ui/InlineToast";
import { copyToClipboard } from "@/lib/utils/clipboard";

interface ToastState {
  variant: InlineToastVariant;
  message: string;
  key: number;
}

export default function KeysPage() {
  const { data: baseUrlData, isLoading: baseUrlLoading } = useBaseUrl();
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const baseUrl = baseUrlData?.baseUrl || "";
  const handleCopyBaseUrl = async () => {
    if (!baseUrl) return;
    const ok = await copyToClipboard(baseUrl);
    if (ok) {
      setCopied(true);
      setToast({ variant: "success", message: "base_url 已复制到剪贴板", key: Date.now() });
      setTimeout(() => setCopied(false), 3000);
    } else {
      setToast({
        variant: "error",
        message: "复制失败，请手动选择上方 base_url 复制",
        key: Date.now(),
      });
    }
  };

  return (
    <div className="space-y-6">
      <InlineToast
        open={toast !== null}
        variant={toast?.variant ?? "success"}
        message={toast?.message ?? ""}
        onClose={() => setToast(null)}
      />

      <h1 className="text-2xl font-bold">sk 管理</h1>

      {/* Base URL display */}
      {!baseUrlLoading && baseUrl && (
        <div className="flex items-center justify-between rounded-md border border-neutral-border bg-neutral-bg px-4 py-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-medium text-neutral-text-primary shrink-0">base_url:</span>
            <code className="text-sm font-mono text-neutral-text-primary truncate select-all">
              {baseUrl}
            </code>
          </div>
          <Button variant="secondary" size="sm" onClick={handleCopyBaseUrl} className="shrink-0 ml-4">
            {copied ? "已复制" : "复制"}
          </Button>
        </div>
      )}

      <CreateKeyForm />
      <KeyList />
    </div>
  );
}
