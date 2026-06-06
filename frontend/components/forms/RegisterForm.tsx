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
import { useRegister } from "@/lib/api/auth";
import { ApiClientError } from "@/lib/api/client";

const registerSchema = z
  .object({
    email: z.string().min(1, "请输入邮箱").email("邮箱格式不正确"),
    password: z.string().min(8, "密码至少8位"),
    confirmPassword: z.string().min(1, "请确认密码"),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "两次密码不一致",
    path: ["confirmPassword"],
  });

type RegisterFormData = z.infer<typeof registerSchema>;

export function RegisterForm() {
  const router = useRouter();
  const register = useRegister();

  const {
    register: registerField,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<RegisterFormData>({
    resolver: zodResolver(registerSchema),
  });

  const onSubmit = async (data: RegisterFormData) => {
    try {
      await register.mutateAsync({
        email: data.email,
        password: data.password,
        confirmPassword: data.confirmPassword,
      });
      router.push("/");
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.code === "EMAIL_EXISTS") {
          setError("email", { message: err.message });
        } else {
          setError("root", { message: err.message });
        }
      } else {
        setError("root", { message: "注册失败，请稍后重试" });
      }
    }
  };

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle>创建 high-api 账号</CardTitle>
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
              placeholder="至少8位"
              autoComplete="new-password"
              error={!!errors.password}
              {...registerField("password")}
            />
            {errors.password && (
              <p className="text-sm text-[#dc2626]">{errors.password.message}</p>
            )}
          </div>

          {/* Confirm Password */}
          <div className="space-y-1.5">
            <Label htmlFor="confirmPassword">确认密码</Label>
            <Input
              id="confirmPassword"
              type="password"
              placeholder="再次输入密码"
              autoComplete="new-password"
              error={!!errors.confirmPassword}
              {...registerField("confirmPassword")}
            />
            {errors.confirmPassword && (
              <p className="text-sm text-[#dc2626]">{errors.confirmPassword.message}</p>
            )}
          </div>

          {/* Root error */}
          {errors.root && (
            <p className="text-sm text-[#dc2626]">{errors.root.message}</p>
          )}

          <Button
            type="submit"
            variant="primary"
            size="md"
            className="w-full"
            disabled={register.isPending}
          >
            {register.isPending ? "注册中..." : "注册"}
          </Button>
        </form>

        <p className="mt-4 text-sm text-center text-neutral-text-secondary">
          已有账号？
          <Link
            href="/login"
            className="ml-1 text-primary-base hover:text-primary-light"
          >
            登录
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
