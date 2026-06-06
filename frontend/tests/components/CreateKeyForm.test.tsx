import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateKeyForm } from "@/components/forms/CreateKeyForm";

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock clipboard
Object.assign(navigator, {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
});

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CreateKeyForm />
    </QueryClientProvider>
  );
}

describe("CreateKeyForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders name input and submit button", () => {
    renderWithProviders();
    expect(screen.getByLabelText("密钥名称")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建 sk" })).toBeInTheDocument();
  });

  it("shows validation error for empty name", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await user.click(screen.getByRole("button", { name: "创建 sk" }));

    await waitFor(() => {
      expect(screen.getByText("请输入密钥名称")).toBeInTheDocument();
    });
  });

  it("shows raw key on successful creation", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 1,
        name: "my-key",
        keyPrefix: "sk-abc123de",
        rawKey: "sk-abc123def456...",
        status: "active",
        createdAt: "2026-05-31T00:00:00Z",
      }),
    });

    renderWithProviders();

    await user.type(screen.getByLabelText("密钥名称"), "my-key");
    await user.click(screen.getByRole("button", { name: "创建 sk" }));

    await waitFor(() => {
      expect(screen.getByText("sk 创建成功")).toBeInTheDocument();
      expect(screen.getByText(/sk-abc123def456\.\.\./)).toBeInTheDocument();
    });
    expect(screen.getByText("复制")).toBeInTheDocument();
  });
});
