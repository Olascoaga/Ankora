import desktopPackage from "../../package.json";
import tauriWindowsConfig from "../../src-tauri/tauri.conf.json";
import tauriLinuxConfig from "../../src-tauri/tauri.linux.conf.json";

describe("Linux desktop development configuration", () => {
  it("adds explicit Linux development scripts consuming scripts/dev_linux.py while preserving Windows scripts", () => {
    expect(desktopPackage.scripts["dev:web"]).toBe(
      "vite --host 127.0.0.1 --port 1420 --configLoader runner",
    );
    expect(desktopPackage.scripts["build:web"]).toBe(
      "tsc -b && vite build --configLoader runner",
    );
    expect(desktopPackage.scripts["dev:tauri-prereq"]).toBe(
      "powershell -ExecutionPolicy Bypass -File ../../scripts/dev.ps1",
    );
    expect(desktopPackage.scripts["tauri:dev"]).toBe("tauri dev");
    expect(desktopPackage.scripts["tauri:build"]).toBe("tauri build --no-bundle");
    expect(desktopPackage.scripts["tauri:installer"]).toBe(
      "powershell -ExecutionPolicy Bypass -File ../../scripts/build_windows_installer.ps1",
    );

    expect(desktopPackage.scripts["dev:linux"]).toBe(
      "python3 ../../scripts/dev_linux.py",
    );
    expect(desktopPackage.scripts["dev:tauri-prereq:linux"]).toBe(
      "python3 ../../scripts/dev_linux.py",
    );
    expect(desktopPackage.scripts["tauri:dev:linux"]).toBe(
      "tauri dev --config src-tauri/tauri.linux.conf.json",
    );
    expect(desktopPackage.scripts["tauri:build:linux"]).toBe(
      "tauri build --no-bundle --config src-tauri/tauri.linux.conf.json",
    );
  });

  it("keeps Linux Tauri configuration separate from Windows installer bundling and preserves strict CSP", () => {
    expect(tauriLinuxConfig.productName).toBe(tauriWindowsConfig.productName);
    expect(tauriLinuxConfig.version).toBe(tauriWindowsConfig.version);
    expect(tauriLinuxConfig.identifier).toBe(tauriWindowsConfig.identifier);

    expect(tauriWindowsConfig.build.beforeDevCommand).toBe("npm run dev:tauri-prereq");
    expect(tauriLinuxConfig.build.beforeDevCommand).toBe(
      "npm run dev:tauri-prereq:linux",
    );
    expect(tauriLinuxConfig.build.devUrl).toBe("http://127.0.0.1:1420");
    expect(tauriLinuxConfig.build.beforeBuildCommand).toBe("npm run build:web");
    expect(tauriLinuxConfig.build.frontendDist).toBe("../dist");

    expect(tauriLinuxConfig.app.security.csp).toBe(
      tauriWindowsConfig.app.security.csp,
    );
    expect(tauriLinuxConfig.app.security.csp).toContain(
      "connect-src 'self' http://127.0.0.1:8765",
    );
    expect(tauriLinuxConfig.app.security.csp).not.toContain("unsafe-eval");

    expect(tauriLinuxConfig.app.windows).toEqual([
      {
        title: "Ankora",
        width: 1280,
        height: 800,
        minWidth: 960,
        minHeight: 680,
        resizable: true,
      },
    ]);

    expect(tauriWindowsConfig.bundle.active).toBe(true);
    expect(tauriWindowsConfig.bundle.targets).toEqual(["nsis"]);
    expect(tauriLinuxConfig.bundle.active).toBe(false);
    expect(tauriLinuxConfig.bundle.targets).toEqual([]);
    expect(tauriLinuxConfig.bundle.licenseFile).toBeNull();
    expect(tauriLinuxConfig.bundle.resources).toBeNull();
  });
});
