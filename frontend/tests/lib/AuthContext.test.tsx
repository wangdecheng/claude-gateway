import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/lib/auth/AuthContext";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

function TestConsumer() {
  const { user, isLoading, isAuthenticated, logout } = useAuth();
  return (
    <div>
      {isLoading && <span>Loading...</span>}
      {isAuthenticated && user && (
        <span data-testid="user-email">{user.email}</span>
      )}
      {isAuthenticated && user && (
        <span data-testid="user-balance">{user.balance}</span>
      )}
      {!isLoading && !isAuthenticated && <span>Not logged in</span>}
      <button onClick={logout}>Logout</button>
    </div>
  );
}

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state initially", async () => {
    // Never resolve the fetch so we stay in loading
    mockFetch.mockReturnValue(new Promise(() => {}));
    renderWithProviders();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows user when /me returns 200", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        user_id: 1,
        email: "auth-test@example.com",
        balance: 1000,
        role: "user",
      }),
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("user-email")).toHaveTextContent("auth-test@example.com");
    });
    expect(screen.getByTestId("user-balance")).toHaveTextContent("1000");
  });

  it("shows not logged in when /me returns 401", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ error: "请先登录", code: "UNAUTHORIZED" }),
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Not logged in")).toBeInTheDocument();
    });
  });

  it("clears user on logout", async () => {
    // First: authenticated
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        user_id: 1,
        email: "logout-auth@example.com",
        balance: 0,
        role: "user",
      }),
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("user-email")).toBeInTheDocument();
    });

    // Mock logout API call
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ message: "已退出登录" }),
    });

    await act(async () => {
      screen.getByText("Logout").click();
    });

    await waitFor(() => {
      expect(screen.getByText("Not logged in")).toBeInTheDocument();
    });
  });
});
