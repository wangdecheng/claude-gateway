"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { BalanceDisplay } from "@/components/data/BalanceDisplay";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/AuthContext";

const NAV_LINKS = [
  { href: "/models", label: "模型" },
  { href: "/keys", label: "sk" },
  { href: "/usage", label: "用量" },
  { href: "/redeem", label: "兑换" },
  { href: "/recharge", label: "充值" },
];

export default function UserLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <div className="min-h-screen">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-10 border-b border-neutral-border bg-neutral-surface">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center justify-between px-6">
          {/* Left: Logo + Nav Links */}
          <div className="flex items-center gap-8">
            <Link
              href="/"
              className="text-lg font-semibold text-primary-base"
            >
              high-api
            </Link>
            <nav className="flex gap-4">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-sm text-neutral-text-secondary transition-colors hover:text-neutral-text-primary"
                >
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>

          {/* Right: Balance + User Menu */}
          <div className="flex items-center gap-4">
            {user && <BalanceDisplay balance={user.balance} />}
            <Link
              href="/settings"
              className="text-sm text-neutral-text-secondary hover:text-neutral-text-primary"
            >
              设置
            </Link>
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              退出
            </Button>
          </div>
        </div>
      </header>

      {/* Page Content */}
      <main className="mx-auto max-w-[1200px] px-6 py-8">{children}</main>
    </div>
  );
}
