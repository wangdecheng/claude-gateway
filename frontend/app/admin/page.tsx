"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdminPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin/models");
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-sm text-neutral-text-secondary">跳转中...</div>
    </div>
  );
}
