import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KeyList } from "@/components/data/KeyList";

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
      <KeyList />
    </QueryClientProvider>
  );
}

describe("KeyList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    renderWithProviders();
    expect(screen.getByText("加载中...")).toBeInTheDocument();
  });

  it("shows empty state when no keys", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("还没有创建 sk")).toBeInTheDocument();
    });
  });

  it("renders list of keys", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          name: "production-key",
          keyPrefix: "sk-a1b2c3de",
          status: "active",
          createdAt: "2026-05-31T00:00:00Z",
          lastUsedAt: null,
        },
        {
          id: 2,
          name: "dev-key",
          keyPrefix: "sk-f5g6h7ij",
          status: "active",
          createdAt: "2026-05-30T00:00:00Z",
          lastUsedAt: "2026-05-31T00:00:00Z",
        },
      ],
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("production-key")).toBeInTheDocument();
      expect(screen.getByText("dev-key")).toBeInTheDocument();
    });

    // Should show masked key prefixes
    expect(screen.getByText("sk-a1**de")).toBeInTheDocument();
    expect(screen.getByText("sk-f5**ij")).toBeInTheDocument();

    // Should show revoke buttons
    const revokeButtons = screen.getAllByText("撤销");
    expect(revokeButtons).toHaveLength(2);
  });
});
