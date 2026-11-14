import { TooltipProvider } from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VaultDocument, VaultSource } from "@/lib/schemas";

const list = vi.fn();
const search = vi.fn();
const reader = vi.fn();
const reindex = vi.fn().mockResolvedValue({});
const remove = vi.fn().mockResolvedValue({});
vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    projects: () => Promise.resolve([{ id: "p1", name: "Apollo" }]),
    settings: () => Promise.resolve({ vault: { use_in_chat: true, local_only: false, max_passages: 4 } }),
    updateSettings: vi.fn(),
    vaultList: (l: unknown) => list(l),
    vaultSearch: (q: string, l: unknown, k: string[]) => search(q, l, k),
    vaultReader: (id: string) => reader(id),
    vaultReindex: (id: string) => reindex(id),
    vaultRemove: (id: string) => remove(id),
    vaultCancel: vi.fn(),
    vaultMove: vi.fn(),
    vaultPickFiles: vi.fn().mockResolvedValue([]),
    vaultCheckChanges: vi.fn().mockResolvedValue(0),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));

const { VaultPage, Snippet, snippetParts, locationLabel } = await import("@/features/vault/Vault");
const { SourceList, unknownCitations } = await import("@/features/vault/Citations");
const { useUi } = await import("@/state/ui");

const doc = (o: Partial<VaultDocument> = {}): VaultDocument => ({
  id: "d1", project_id: null, project_name: null, title: "Annual report", file_name: "report.pdf", source_path: "/x/report.pdf", kind: "pdf", size_bytes: 2048,
  content_hash: "h", status: "indexed", error: null, pages: 12, sections: 12, chunks: 30, chars: 9000, extractor_version: 1, index_version: 1,
  imported_at: new Date().toISOString(), updated_at: new Date().toISOString(), indexed_at: new Date().toISOString(), opened_at: null, ...o,
});
const stats = { documents: 2, indexed: 1, processing: 0, failed: 1, needs_reindex: 0, passages: 30, storage_bytes: 4096 };
const src = (o: Partial<VaultSource> = {}): VaultSource => ({ label: "S1", chunk_id: "c1", document_id: "d1", title: "Annual report", kind: "pdf", page: 3, heading: "", excerpt: "…", sent: true, ...o });

const page = () => render(<TooltipProvider><VaultPage /></TooltipProvider>);

describe("Knowledge Vault", () => {
  beforeEach(() => {
    list.mockReset();
    search.mockReset();
    reader.mockReset();
    useUi.setState({ vaultOpen: null });
  });

  it("marks matches without ever rendering document text as markup", () => {
    expect(snippetParts("a \u0002b\u0003 c")).toEqual([{ text: "a ", match: false }, { text: "b", match: true }, { text: " c", match: false }]);
    const { container } = render(<Snippet text={"<img src=x onerror=alert(1)> \u0002budget\u0003"} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.querySelector("mark")?.textContent).toBe("budget");
    expect(locationLabel(3, "")).toBe("page 3");
    expect(locationLabel(null, "A › B")).toBe("A › B");
    expect(locationLabel(null, "")).toBe("no page or heading");
  });

  it("lists documents with their status, shows failures apart, and retries", async () => {
    list.mockResolvedValue({ documents: [doc(), doc({ id: "d2", title: "scan", status: "failed", chunks: 0, pages: null, error: "This PDF has no text layer" })], stats });
    page();
    await screen.findByText("Annual report");
    expect(document.querySelector('[data-vault-doc="Annual report"]')?.getAttribute("data-status")).toBe("indexed");
    const failed = screen.getByRole("region", { name: "Failed imports" });
    expect(failed.textContent).toContain("This PDF has no text layer");
    fireEvent.click(screen.getByRole("button", { name: "Retry scan" }));
    await waitFor(() => expect(reindex).toHaveBeenCalledWith("d2"));
    expect(screen.getByText("30")).toBeTruthy();
  });

  it("explains an empty Vault", async () => {
    list.mockResolvedValue({ documents: [], stats: { ...stats, documents: 0, indexed: 0, failed: 0, passages: 0 } });
    page();
    expect(await screen.findByText("Your Knowledge Vault is empty")).toBeTruthy();
  });

  it("searches the chosen library and types, and opens a result at its passage", async () => {
    list.mockResolvedValue({ documents: [doc()], stats });
    search.mockResolvedValue([{ chunk_id: "c9", document_id: "d1", title: "Annual report", kind: "pdf", project_id: null, page: 7, heading: "", snippet: "the \u0002glacier\u0003 budget", content: "", score: 1, matched_terms: 1 }]);
    page();
    await screen.findByText("Annual report");
    fireEvent.change(screen.getByLabelText("Library"), { target: { value: "personal" } });
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    fireEvent.change(screen.getByLabelText("Search the Knowledge Vault"), { target: { value: "glacier" } });
    await waitFor(() => expect(search).toHaveBeenCalledWith("glacier", { kind: "personal" }, ["pdf"]));
    const hit = await screen.findByText("page 7");
    reader.mockResolvedValue({ document: doc(), parts: [{ chunk_id: "c9", seq: 0, page: 7, heading: "", text: "The glacier budget is 40000." }] });
    fireEvent.click(hit);
    expect(useUi.getState().vaultOpen).toEqual({ documentId: "d1", chunkId: "c9", page: 7, heading: "" });
    await waitFor(() => expect(document.querySelector('[data-cited="true"]')?.textContent).toBe("The glacier budget is 40000."));
  });

  it("asks before removing, and says the original file is kept", async () => {
    list.mockResolvedValue({ documents: [doc()], stats });
    page();
    await screen.findByText("Annual report");
    fireEvent.click(screen.getByRole("button", { name: "Remove Annual report" }));
    expect(await screen.findByText(/Your original file is not touched/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("d1"));
  });
});

describe("Citations", () => {
  it("lists only the passages really given, opens them, and flags citations that match none", () => {
    expect(unknownCitations("As [S1] and [S4] say", [src()])).toEqual(["S4"]);
    expect(unknownCitations("[S1]", [src({ sent: false })])).toEqual(["S1"]);
    render(<SourceList sources={[src(), src({ label: "S2", document_id: null, title: "Old notes", page: null, heading: "Intro" })]} reply="It costs 40000 [S1]. Also [S7]." />);
    expect(screen.getByText("Answered with 2 passages from your Knowledge Vault")).toBeTruthy();
    expect(document.querySelector('[data-source="S1"]')?.getAttribute("data-cited")).toBe("true");
    expect(screen.getByText("removed")).toBeTruthy();
    expect(document.querySelector("[data-unknown-citations]")?.textContent).toContain("[S7]");
    fireEvent.click(screen.getByText("Annual report"));
    expect(useUi.getState().vaultOpen).toEqual({ documentId: "d1", chunkId: "c1", page: 3, heading: "" });
  });

  it("says when local-only held passages back", () => {
    render(<SourceList sources={[src({ sent: false })]} reply="I could not see your documents." />);
    expect(screen.getByText("Relevant passages were found but not sent")).toBeTruthy();
    expect(screen.getByText("held back (local-only)")).toBeTruthy();
  });
});
