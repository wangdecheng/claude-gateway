import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import KeysPage from "@/app/(user)/keys/page";

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
      <KeysPage />
    </QueryClientProvider>
  );
}

describe("KeysPage - baseUrl display", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation((url: string) => {
      if (url.includes("/public-url")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ baseUrl: "https://gateway.example.com" }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => [],
      });
    });
  });

  it("renders baseUrl section with copy button", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("base_url:")).toBeInTheDocument();
      expect(screen.getByText("https://gateway.example.com")).toBeInTheDocument();
    });
  });

  it("changes button text to 已复制 after clicking copy", async () => {
    const user = userEvent.setup();

    renderWithProviders();

    await screen.findByText("https://gateway.example.com");

    await user.click(screen.getByRole("button", { name: "复制" }));

    // After successful copy, button text should change
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    });
  });
});
