"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateKey } from "@/lib/api/keys";
import { ApiClientError } from "@/lib/api/client";

const schema = z.object({
  name: z.string().min(1, "请输入密钥名称").max(100, "名称最多100个字符"),
});

type FormData = z.infer<typeof schema>;

export function CreateKeyForm() {
  const mutation = useCreateKey();
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
    reset,
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    try {
      const result = await mutation.mutateAsync({ name: data.name });
      setRawKey(result.rawKey);
      reset();
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError("root", { message: err.message });
      } else {
        setError("root", { message: "创建失败，请稍后重试" });
      }
    }
  };

  const handleCopy = async () => {
    if (!rawKey) return;
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  if (rawKey) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-[#16a34a]">sk 创建成功</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md bg-[#fef2f2] border border-[#fecaca] p-4">
            <p className="text-sm font-medium text-[#dc2626] mb-2">
              ⚠️ 请立即复制此密钥，关闭后将无法再次查看
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-neutral-bg px-3 py-2 font-mono text-sm text-neutral-text-primary select-all">
                {rawKey}
              </code>
              <Button variant="secondary" size="sm" onClick={handleCopy} className="shrink-0">
                {copied ? "已复制" : "复制"}
              </Button>
            </div>
          </div>
          <Button
            variant="primary"
            size="md"
            className="w-full"
            onClick={() => setRawKey(null)}
          >
            知道了
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>创建 sk</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="keyName">密钥名称</Label>
            <Input
              id="keyName"
              placeholder="例如: production-key, dev-key"
              error={!!errors.name}
              {...register("name")}
            />
            {errors.name && (
              <p className="text-sm text-[#dc2626]">{errors.name.message}</p>
            )}
          </div>

          {errors.root && (
            <p className="text-sm text-[#dc2626]">{errors.root.message}</p>
          )}

          <Button type="submit" variant="primary" size="md" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? "创建中..." : "创建 sk"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
