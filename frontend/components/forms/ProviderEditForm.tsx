"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AdminProviderItem, ProviderCreateInput, ProviderUpdateInput } from "@/lib/api/admin/providers";

interface ProviderEditFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: ProviderCreateInput | ProviderUpdateInput) => Promise<void>;
  provider?: AdminProviderItem | null; // null = create mode
  isSubmitting: boolean;
  error?: string | null;
}

interface FormValues {
  name: string;
  channelName: string;
  multiplier: number;
  apiBaseUrl: string;
  authHeader: string;
  adapter: string;
  keys: string;
}

export function ProviderEditForm({
  open,
  onOpenChange,
  onSubmit,
  provider,
  isSubmitting,
  error,
}: ProviderEditFormProps) {
  const isEdit = !!provider;

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      name: "",
      channelName: "",
      multiplier: 1.0,
      apiBaseUrl: "",
      authHeader: "Authorization",
      adapter: "anthropic-messages",
      keys: "",
    },
  });

  const adapterValue = watch("adapter");

  useEffect(() => {
    if (open) {
      if (provider) {
        reset({
          name: provider.name,
          channelName: provider.channelName,
          multiplier: provider.multiplier,
          apiBaseUrl: provider.apiBaseUrl,
          authHeader: provider.authHeader,
          adapter: provider.adapter,
          keys: "",
        });
      } else {
        reset({
          name: "",
          channelName: "",
          multiplier: 1.0,
          apiBaseUrl: "",
          authHeader: "Authorization",
          adapter: "openai-chat-completions",
          keys: "",
        });
      }
    }
  }, [open, provider, reset]);

  const onFormSubmit = async (values: FormValues) => {
    const keyList = values.keys
      .split("\n")
      .map((k) => k.trim())
      .filter(Boolean);

    if (isEdit) {
      // Name is intentionally not editable (preserves SK bindings)
      const data: ProviderUpdateInput = {
        channelName: values.channelName,
        multiplier: Number(values.multiplier),
        apiBaseUrl: values.apiBaseUrl,
        authHeader: values.authHeader,
        adapter: values.adapter,
      };
      await onSubmit(data);
    } else {
      const data: ProviderCreateInput = {
        name: values.name,
        channelName: values.channelName,
        multiplier: Number(values.multiplier),
        apiBaseUrl: values.apiBaseUrl,
        authHeader: values.authHeader,
        adapter: values.adapter,
        keys: keyList.length > 0 ? keyList : undefined,
      };
      await onSubmit(data);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑供应商" : "添加供应商"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "修改供应商的渠道名、倍率、API URL 与认证配置。"
              : "添加一个新的上游 AI 供应商。每个 (供应商名, 渠道名) 组合必须唯一。"}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onFormSubmit)} className="space-y-4">
          {/* Name — editable only on create (changing it would break SK bindings) */}
          <div className="space-y-2">
            <Label htmlFor="name">
              供应商名称{!isEdit && <span className="text-red-500"> *</span>}
            </Label>
            {isEdit ? (
              <>
                <Input
                  id="name"
                  readOnly
                  value={provider?.name ?? ""}
                  className="bg-muted cursor-not-allowed"
                />
                <p className="text-xs text-neutral-text-secondary">
                  供应商名称不可修改（影响 Key 绑定），只能调整渠道名。
                </p>
              </>
            ) : (
              <>
                <Input
                  id="name"
                  placeholder="如 Anthropic、DeepSeek"
                  {...register("name", { required: "请输入供应商名称" })}
                />
                {errors.name && (
                  <p className="text-sm text-red-500">{errors.name.message}</p>
                )}
              </>
            )}
          </div>

          {/* Channel name + Multiplier */}
          <div className="grid grid-cols-[1fr_120px] gap-4">
            <div className="space-y-2">
              <Label htmlFor="channelName">渠道名 *</Label>
              <Input
                id="channelName"
                placeholder="如 主力线路 / awsq"
                {...register("channelName", {
                  required: "请输入渠道名",
                  minLength: { value: 1, message: "渠道名不能为空" },
                })}
              />
              {errors.channelName && (
                <p className="text-sm text-red-500">{errors.channelName.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="multiplier">倍率 *</Label>
              <Input
                id="multiplier"
                type="number"
                step="0.01"
                min="0.01"
                {...register("multiplier", {
                  required: "请输入倍率",
                  valueAsNumber: true,
                  validate: (v) => (v > 0 ? true : "倍率必须大于 0"),
                })}
              />
              {errors.multiplier && (
                <p className="text-sm text-red-500">{errors.multiplier.message}</p>
              )}
            </div>
          </div>
          <p className="text-xs text-neutral-text-secondary">
            渠道名 + 倍率构成"渠道"。最终费用 = 模型基础价 × 渠道倍率。
          </p>

          {/* API Base URL */}
          <div className="space-y-2">
            <Label htmlFor="apiBaseUrl">API Base URL *</Label>
            <Input
              id="apiBaseUrl"
              placeholder="https://api.anthropic.com"
              className="font-mono text-sm"
              {...register("apiBaseUrl", { required: "请输入 API Base URL" })}
            />
            {errors.apiBaseUrl && (
              <p className="text-sm text-red-500">{errors.apiBaseUrl.message}</p>
            )}
          </div>

          {/* Auth Header + Adapter */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="authHeader">认证头</Label>
              <Select
                value={watch("authHeader")}
                onValueChange={(v) => setValue("authHeader", v)}
              >
                <SelectTrigger id="authHeader">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Authorization">Authorization (Bearer)</SelectItem>
                  <SelectItem value="x-api-key">x-api-key</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="adapter">协议适配器</Label>
              <Select
                value={adapterValue}
                onValueChange={(v) => setValue("adapter", v)}
              >
                <SelectTrigger id="adapter">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai-chat-completions">
                    OpenAI Chat Completions
                  </SelectItem>
                  <SelectItem value="anthropic-messages">
                    Anthropic Messages
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Keys — create mode only */}
          {!isEdit && (
            <div className="space-y-2">
              <Label htmlFor="keys">
                上游 API Key（可选，每行一把 Key）
              </Label>
              <Textarea
                id="keys"
                rows={3}
                placeholder={"sk-ant-api03-xxxxx\ndeepseek-api-key-xxxxx"}
                className="font-mono text-sm"
                {...register("keys")}
              />
              <p className="text-xs text-neutral-text-secondary">
                Key 将使用 AES-256-GCM 加密存储，后续可在 Key 管理中继续添加。
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "保存中..." : isEdit ? "保存修改" : "添加供应商"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
