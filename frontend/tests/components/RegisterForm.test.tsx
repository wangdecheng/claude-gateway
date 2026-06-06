import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RegisterForm } from "@/components/forms/RegisterForm";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RegisterForm />
    </QueryClientProvider>
  );
}

describe("RegisterForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all form fields", () => {
    renderWithProviders();

    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByLabelText("确认密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "注册" })).toBeInTheDocument();
  });

  it("shows validation error for short password on submit", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("邮箱"), "test@example.com");
    await user.type(screen.getByLabelText("密码"), "123");
    await user.type(screen.getByLabelText("确认密码"), "123");
    await user.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => {
      expect(screen.getByText("密码至少8位")).toBeInTheDocument();
    });
  });

  it("shows validation error for mismatched passwords", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("邮箱"), "test@example.com");
    await user.type(screen.getByLabelText("密码"), "securepass123");
    await user.type(screen.getByLabelText("确认密码"), "differentpass");
    await user.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => {
      expect(screen.getByText("两次密码不一致")).toBeInTheDocument();
    });
  });

  it("shows validation error for invalid email", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("邮箱"), "notanemail");
    await user.type(screen.getByLabelText("密码"), "securepass123");
    await user.type(screen.getByLabelText("确认密码"), "securepass123");
    await user.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => {
      expect(screen.getByText("邮箱格式不正确")).toBeInTheDocument();
    });
  });

  it("renders link to login page", () => {
    renderWithProviders();
    const loginLink = screen.getByRole("link", { name: "登录" });
    expect(loginLink).toBeInTheDocument();
    expect(loginLink).toHaveAttribute("href", "/login");
  });
});
