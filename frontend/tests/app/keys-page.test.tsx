import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import KeysPage from "@/app/(user)/keys/page";

const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockCopyToClipboard = vi.fn<(text: string) => Promise<boolean>>();
vi.mock("@/lib/utils/clipboard", () => ({
  copyToClipboard: (text: string) => mockCopyToClipboard(text),
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
      <KeysPage />
    </QueryClientProvider>
  );
}

describe("KeysPage - baseUrl display", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockCopyToClipboard.mockReset();
    mockCopyToClipboard.mockResolvedValue(true);
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

  it("shows success toast and flips button text on successful copy", async () => {
    const user = userEvent.setup();
    renderWithProviders();

    await screen.findByText("https://gateway.example.com");
    await user.click(screen.getByRole("button", { name: "复制" }));

    expect(await screen.findByText("base_url 已复制到剪贴板")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    });
    expect(mockCopyToClipboard).toHaveBeenCalledWith("https://gateway.example.com");
  });

  it("shows error toast when copy fails", async () => {
    const user = userEvent.setup();
    mockCopyToClipboard.mockResolvedValue(false);

    renderWithProviders();

    await screen.findByText("https://gateway.example.com");
    await user.click(screen.getByRole("button", { name: "复制" }));

    expect(
      await screen.findByText("复制失败，请手动选择上方 base_url 复制")
    ).toBeInTheDocument();
    // Button stays as "复制", does NOT flip to "已复制".
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument();
  });
});
