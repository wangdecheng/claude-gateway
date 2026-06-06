"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLogin } from "@/lib/api/auth";
import { ApiClientError } from "@/lib/api/client";

const loginSchema = z.object({
  email: z.string().min(1, "请输入邮箱").email("邮箱格式不正确"),
  password: z.string().min(1, "请输入密码"),
});

type LoginFormData = z.infer<typeof loginSchema>;

export function LoginForm() {
  const router = useRouter();
  const login = useLogin();

  const {
    register: registerField,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    try {
      await login.mutateAsync({
        email: data.email,
        password: data.password,
      });
      router.push("/");
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError("root", { message: err.message });
      } else {
        setError("root", { message: "登录失败，请稍后重试" });
      }
    }
  };

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>登录 high-api</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          {/* Email */}
          <div className="space-y-1.5">
            <Label htmlFor="email">邮箱</Label>
            <Input
              id="email"
              type="email"
              placeholder="dev@example.com"
              autoComplete="email"
              error={!!errors.email}
              {...registerField("email")}
            />
            {errors.email && (
              <p className="text-sm text-[#dc2626]">{errors.email.message}</p>
            )}
          </div>

          {/* Password */}
          <div className="space-y-1.5">
            <Label htmlFor="password">密码</Label>
            <Input
              id="password"
              type="password"
              placeholder="输入密码"
              autoComplete="current-password"
              error={!!errors.password}
              {...registerField("password")}
            />
            {errors.password && (
              <p className="text-sm text-[#dc2626]">{errors.password.message}</p>
            )}
          </div>

          {/* Forgot password */}
          <p className="text-right">
            <Link
              href="/forgot-password"
              className="text-xs text-primary-base hover:text-primary-light"
            >
              忘记密码？
            </Link>
          </p>

          {/* Root error */}
          {errors.root && (
            <p className="text-sm text-[#dc2626]">{errors.root.message}</p>
          )}

          <Button
            type="submit"
            variant="primary"
            size="md"
            className="w-full"
            disabled={login.isPending}
          >
            {login.isPending ? "登录中..." : "登录"}
          </Button>
        </form>

        <p className="mt-4 text-sm text-center text-neutral-text-secondary">
          还没有账号？
          <Link
            href="/register"
            className="ml-1 text-primary-base hover:text-primary-light"
          >
            注册
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
