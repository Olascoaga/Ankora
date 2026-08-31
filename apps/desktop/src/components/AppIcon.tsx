import type { ReactNode, SVGProps } from "react";

export type AppIconName =
  | "activity"
  | "alert"
  | "chevron"
  | "close-panel"
  | "file"
  | "help"
  | "history"
  | "info"
  | "layout"
  | "menu"
  | "molecule"
  | "panel-left"
  | "panel-right"
  | "provenance"
  | "settings"
  | "success"
  | "tools";

interface AppIconProps extends SVGProps<SVGSVGElement> {
  name: AppIconName;
}

export function AppIcon({ name, ...props }: AppIconProps) {
  const paths: Record<AppIconName, ReactNode> = {
    activity: <><path d="M4 12h3l2-6 4 12 2-6h5" /><path d="M3 4v16h18" /></>,
    alert: <><path d="M12 3 2.8 20h18.4L12 3Z" /><path d="M12 9v5" /><path d="M12 17.2v.1" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    "close-panel": <><path d="M4 5h16v14H4z" /><path d="m10 9 6 6m0-6-6 6" /></>,
    file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h5" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.7 9a2.5 2.5 0 1 1 3.4 2.3c-.8.4-1.1.9-1.1 1.7" /><path d="M12 17v.1" /></>,
    history: <><path d="M4 5v5h5" /><path d="M5.3 9A8 8 0 1 1 6 17" /><path d="M12 7v5l3 2" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6" /><path d="M12 7v.1" /></>,
    layout: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 4v16M16 4v16M8 15h8" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    molecule: <><path d="m8 5 4-2 4 2v5l4 2v5l-4 2-4-2-4 2-4-2v-5l4-2V5Z" /><path d="m8 10 4 2 4-2M12 12v5" /></>,
    "panel-left": <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
    "panel-right": <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></>,
    provenance: <><circle cx="6" cy="6" r="2" /><circle cx="18" cy="18" r="2" /><path d="M8 6h4a4 4 0 0 1 4 4v6M6 8v8a2 2 0 0 0 2 2h8" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19 13.5v-3l-2-.7a7 7 0 0 0-.7-1.7l.9-1.9-2.1-2.1-1.9.9a7 7 0 0 0-1.7-.7L10.5 2h-3l-.7 2a7 7 0 0 0-1.7.7l-1.9-.9-2.1 2.1.9 1.9a7 7 0 0 0-.7 1.7L0 10.5v3l2 .7a7 7 0 0 0 .7 1.7l-.9 1.9 2.1 2.1 1.9-.9a7 7 0 0 0 1.7.7l.7 2h3l.7-2a7 7 0 0 0 1.7-.7l1.9.9 2.1-2.1-.9-1.9a7 7 0 0 0 .7-1.7Z" transform="translate(2.5) scale(.8)" /></>,
    success: <><circle cx="12" cy="12" r="9" /><path d="m8 12 2.7 2.7L16.5 9" /></>,
    tools: <><path d="m14 6 4-3 3 3-3 4" /><path d="M16 8 6 18l-3 1 1-3L14 6" /><path d="m7 5 3 3" /></>,
  };
  return <svg
    aria-hidden="true"
    fill="none"
    height="18"
    viewBox="0 0 24 24"
    width="18"
    {...props}
  >
    <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7">{paths[name]}</g>
  </svg>;
}
