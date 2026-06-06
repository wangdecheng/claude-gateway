import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock AuthContext
vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({ refetch: vi.fn() }),
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
      <ChangePasswordForm />
    </QueryClientProvider>
  );
}

describe("ChangePasswordForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all form fields", () => {
    renderWithProviders();
    expect(screen.getByLabelText("当前密码")).toBeInTheDocument();
    expect(screen.getByLabelText("新密码")).toBeInTheDocument();
    expect(screen.getByLabelText("确认新密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "修改密码" })).toBeInTheDocument();
  });

  it("shows validation error for short new password", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("当前密码"), "oldpass123");
    await user.type(screen.getByLabelText("新密码"), "123");
    await user.type(screen.getByLabelText("确认新密码"), "123");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    await waitFor(() => {
      expect(screen.getByText("密码至少8位")).toBeInTheDocument();
    });
  });

  it("shows validation error for mismatched passwords", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.type(screen.getByLabelText("当前密码"), "oldpass123");
    await user.type(screen.getByLabelText("新密码"), "newpass456");
    await user.type(screen.getByLabelText("确认新密码"), "different");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    await waitFor(() => {
      expect(screen.getByText("两次密码不一致")).toBeInTheDocument();
    });
  });

  it("shows success message on successful change", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ message: "密码已修改" }),
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("当前密码"), "oldpass123");
    await user.type(screen.getByLabelText("新密码"), "newpass456");
    await user.type(screen.getByLabelText("确认新密码"), "newpass456");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    await waitFor(() => {
      expect(screen.getByText("密码修改成功")).toBeInTheDocument();
    });
  });
});
