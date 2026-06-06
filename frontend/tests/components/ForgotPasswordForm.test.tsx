import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ForgotPasswordForm } from "@/components/forms/ForgotPasswordForm";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ForgotPasswordForm />
    </QueryClientProvider>
  );
}

describe("ForgotPasswordForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email field and submit button", () => {
    renderWithProviders();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送重置链接" })).toBeInTheDocument();
  });

  it("shows validation error for invalid email", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("邮箱"), "notanemail");
    await user.click(screen.getByRole("button", { name: "发送重置链接" }));

    await waitFor(() => {
      expect(screen.getByText("邮箱格式不正确")).toBeInTheDocument();
    });
  });

  it("shows success message and dev token after submit", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        message: "如果该邮箱已注册，重置链接已发送",
        token: "dev-reset-token-123",
      }),
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("邮箱"), "test@example.com");
    await user.click(screen.getByRole("button", { name: "发送重置链接" }));

    await waitFor(() => {
      expect(screen.getByText(/重置链接已发送/)).toBeInTheDocument();
      expect(screen.getByText("dev-reset-token-123")).toBeInTheDocument();
    });
    expect(screen.getByText("返回登录")).toBeInTheDocument();
  });
});
