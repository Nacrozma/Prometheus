import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Markdown } from "@/components/Markdown";

vi.mock("@/lib/bridge", () => ({ isTauri: () => false, api: { openExternal: vi.fn() } }));

describe("Markdown (untrusted model output)", () => {
  it("never renders raw HTML", () => {
    const { container } = render(<Markdown text={'Hi <script>alert(1)</script><img src=x onerror="alert(2)"> <b>bold</b>'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("neutralises javascript: links and keeps https links", () => {
    const { container } = render(<Markdown text={"[bad](javascript:alert(1)) and [good](https://example.com/a)"} />);
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/a"]);
    expect(container.textContent).toContain("bad");
  });

  it("does not fetch remote images", () => {
    const { container } = render(<Markdown text={"![tracker](https://evil.example/pixel.png)"} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("[image: tracker]");
  });

  it("renders code blocks with a language label", () => {
    const { container, getByText } = render(<Markdown text={"```rust\nfn main() {}\n```"} />);
    expect(getByText("rust")).toBeInTheDocument();
    expect(container.querySelector("pre code")).not.toBeNull();
  });
});
