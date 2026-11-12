import { fireEvent, render, screen } from "@testing-library/react";

import * as chooseGninaPack from "../features/docking/chooseGninaPack";
import { GninaOfflinePackControl } from "../features/docking/GninaOfflinePackControl";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("stays hidden when GNINA is already available", () => {
  const { container } = render(
    <GninaOfflinePackControl
      gnina={{ available: true, path: "/opt/gnina", version: "1.3.3" }}
    />,
  );
  expect(container).toBeEmptyDOMElement();
});

it("disables the offline pack button outside the Tauri desktop shell with an explanation", () => {
  vi.spyOn(chooseGninaPack, "gninaPackChooserAvailable").mockReturnValue(false);
  render(
    <GninaOfflinePackControl
      gnina={{ available: false, path: null, version: null }}
    />,
  );

  const button = screen.getByRole("button", { name: "Import offline GNINA pack…" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("title", expect.stringContaining("desktop app"));
});

it("imports the selected offline pack archive and refreshes tool availability", async () => {
  vi.spyOn(chooseGninaPack, "gninaPackChooserAvailable").mockReturnValue(true);
  vi.spyOn(chooseGninaPack, "chooseGninaPackArchive").mockResolvedValue(
    "/tmp/Ankora_0.1.0_gnina-cuda12-pack.tar.zst",
  );
  const onToolsRefresh = vi.fn().mockResolvedValue(undefined);
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    json({
      supported: true,
      installed: true,
      pack_id: "gnina-1.3.3-cuda12.8-cudnn9.25-linux-x86_64",
      gnina_version: "1.3.3",
      install_dir: "/tmp/toolchains/gnina-1.3.3-cuda12",
      executable_path: "/tmp/toolchains/gnina-1.3.3-cuda12/bin/gnina",
      executable_sha256: "3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172",
      shared_library_count: 17,
      imported_at: "2026-11-11T20:00:00Z",
    }),
  );

  render(
    <GninaOfflinePackControl
      gnina={{ available: false, path: null, version: null }}
      onToolsRefresh={onToolsRefresh}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Import offline GNINA pack…" }));

  await screen.findByText("GNINA 1.3.3 offline pack verified");
  expect(
    screen.getByText(/17 isolated CUDA 12\.8 \/ cuDNN 9\.25 libraries ready/),
  ).toBeInTheDocument();
  expect(onToolsRefresh).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
  expect(url).toContain("/tools/gnina-pack/import");
  expect(JSON.parse(String(init.body))).toEqual({
    archive_path: "/tmp/Ankora_0.1.0_gnina-cuda12-pack.tar.zst",
  });
});

it("surfaces backend cryptographic verification errors without refreshing tools", async () => {
  vi.spyOn(chooseGninaPack, "gninaPackChooserAvailable").mockReturnValue(true);
  vi.spyOn(chooseGninaPack, "chooseGninaPackArchive").mockResolvedValue(
    "/tmp/corrupted-pack.tar.zst",
  );
  const onToolsRefresh = vi.fn();
  vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    json(
      {
        code: "GNINA_PACK_HASH_MISMATCH",
        stage: "gnina_pack",
        message: "Cryptographic SHA-256 mismatch for bin/gnina.",
        details: {},
        recoverable: false,
      },
      422,
    ),
  );

  render(
    <GninaOfflinePackControl
      gnina={{ available: false, path: null, version: null }}
      onToolsRefresh={onToolsRefresh}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Import offline GNINA pack…" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Cryptographic SHA-256 mismatch for bin/gnina.",
  );
  expect(onToolsRefresh).not.toHaveBeenCalled();
});
