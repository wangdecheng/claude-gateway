import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// We test the hook structure and types by mocking apiClient
import * as clientModule from "@/lib/api/client";

// Mock the apiClient before importing hooks
vi.mock("@/lib/api/client", () => ({
  apiClient: vi.fn(),
  ApiClientError: class extends Error {
    code: string;
    status: number;
    constructor({ error, code, status }: { error: string; code: string; status: number }) {
      super(error);
      this.code = code;
      this.status = status;
    }
  },
}));

// Dynamic import after mock
const { useUsageStats, useUsageHistory } = await import("@/lib/api/usage");

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

describe("useUsageStats", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("fetches usage stats with default days", async () => {
    const mockData = {
      todayCalls: 5,
      todayTokens: 1000,
      todayCostCents: 50,
      activeKeys: 2,
      daily: [],
    };
    vi.mocked(clientModule.apiClient).mockResolvedValueOnce(mockData);

    const { result } = renderHook(() => useUsageStats(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockData);
    expect(clientModule.apiClient).toHaveBeenCalledWith("/usage/stats?days=30");
  });

  it("fetches usage stats with custom days", async () => {
    const mockData = {
      todayCalls: 0,
      todayTokens: 0,
      todayCostCents: 0,
      activeKeys: 0,
      daily: [],
    };
    vi.mocked(clientModule.apiClient).mockResolvedValueOnce(mockData);

    const { result } = renderHook(() => useUsageStats(7), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(clientModule.apiClient).toHaveBeenCalledWith("/usage/stats?days=7");
  });
});

describe("useUsageHistory", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("fetches usage history with default pagination", async () => {
    const mockData = {
      records: [],
      total: 0,
      page: 1,
      pageSize: 20,
    };
    vi.mocked(clientModule.apiClient).mockResolvedValueOnce(mockData);

    const { result } = renderHook(() => useUsageHistory(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockData);
    expect(clientModule.apiClient).toHaveBeenCalledWith(
      "/usage/history?page=1&pageSize=20"
    );
  });

  it("fetches usage history with custom pagination", async () => {
    const mockData = {
      records: [],
      total: 0,
      page: 2,
      pageSize: 10,
    };
    vi.mocked(clientModule.apiClient).mockResolvedValueOnce(mockData);

    const { result } = renderHook(() => useUsageHistory(2, 10), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(clientModule.apiClient).toHaveBeenCalledWith(
      "/usage/history?page=2&pageSize=10"
    );
  });
});
