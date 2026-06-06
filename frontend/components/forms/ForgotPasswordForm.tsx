"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useForgotPassword } from "@/lib/api/auth";
import { ApiClientError } from "@/lib/api/client";

const schema = z.object({
  email: z.string().min(1, "请输入邮箱").email("邮箱格式不正确"),
});

type FormData = z.infer<typeof schema>;

export function ForgotPasswordForm() {
  const mutation = useForgotPassword();

  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    try {
      await mutation.mutateAsync({ email: data.email });
    } catch {
      setError("root", { message: "发送失败，请稍后重试" });
    }
  };

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>忘记密码</CardTitle>
      </CardHeader>
      <CardContent>
        {mutation.isSuccess ? (
          <div className="space-y-4">
            <p className="text-sm text-[#16a34a]">
              如果该邮箱已注册，重置链接已发送到您的邮箱。
            </p>
            {mutation.data?.token && (
              <div className="space-y-1.5 rounded-md bg-neutral-subtle p-3">
                <Label className="text-xs text-neutral-text-secondary">
                  开发模式 — 重置令牌
                </Label>
                <code className="block break-all text-xs font-mono text-neutral-text-primary">
                  {mutation.data.token}
                </code>
              </div>
            )}
            <Link
              href="/login"
              className="inline-block text-sm text-primary-base hover:text-primary-light"
            >
              返回登录
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                placeholder="dev@example.com"
                autoComplete="email"
                error={!!errors.email}
                {...register("email")}
              />
              {errors.email && (
                <p className="text-sm text-[#dc2626]">{errors.email.message}</p>
              )}
            </div>

            {errors.root && (
              <p className="text-sm text-[#dc2626]">{errors.root.message}</p>
            )}

            <Button type="submit" variant="primary" size="md" className="w-full" disabled={mutation.isPending}>
              {mutation.isPending ? "发送中..." : "发送重置链接"}
            </Button>

            <p className="text-sm text-center text-neutral-text-secondary">
              <Link href="/login" className="text-primary-base hover:text-primary-light">
                返回登录
              </Link>
            </p>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
