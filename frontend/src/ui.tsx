import type { ButtonHTMLAttributes, ReactElement, SVGProps } from "react";

export type IconName =
  | "projects" | "batch" | "layout" | "settings" | "back" | "plus"
  | "search" | "filter" | "more" | "check" | "alert" | "clock"
  | "play" | "pause" | "download" | "upload" | "zoom-in" | "zoom-out"
  | "fit" | "hand" | "eye" | "eye-off" | "lock" | "unlock" | "layers"
  | "undo" | "redo" | "preview" | "close" | "chevron-down" | "grip"
  | "image" | "review" | "export" | "profile" | "plan" | "refresh"
  | "trash" | "copy" | "edit" | "info" | "type";

export function Icon({ name, size = 18, ...props }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  const paths: Record<IconName, ReactElement> = {
    type: <><path d="M5 5h14M12 5v14M8 19h8"/></>,
    projects: <><path d="M3.5 7.5h17v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M3.5 7.5V5.8a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2"/></>,
    batch: <><path d="m12 3 8 4.5-8 4.5-8-4.5z"/><path d="m4 12 8 4.5 8-4.5"/><path d="m4 16.5 8 4.5 8-4.5"/></>,
    layout: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    settings: <><path d="M4 6h7M15 6h5M4 12h3M11 12h9M4 18h10M18 18h2"/><circle cx="13" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="18" r="2"/></>,
    back: <><path d="m15 18-6-6 6-6"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></>,
    filter: <><path d="M4 5h16l-6.5 7.2V19l-3 1v-7.8z"/></>,
    more: <><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
    alert: <><path d="M10.3 4.1 2.8 18a2 2 0 0 0 1.8 3h14.8a2 2 0 0 0 1.8-3L13.7 4.1a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    play: <><path d="m8 5 11 7-11 7z"/></>,
    pause: <><path d="M9 5v14M15 5v14"/></>,
    download: <><path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 20h16"/></>,
    upload: <><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/></>,
    "zoom-in": <><circle cx="10.5" cy="10.5" r="6.5"/><path d="M8 10.5h5M10.5 8v5M16 16l4.5 4.5"/></>,
    "zoom-out": <><circle cx="10.5" cy="10.5" r="6.5"/><path d="M8 10.5h5M16 16l4.5 4.5"/></>,
    fit: <><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></>,
    hand: <><path d="M8.5 11V6.5a1.5 1.5 0 0 1 3 0V10M11.5 10V5a1.5 1.5 0 0 1 3 0v5M14.5 10V6.5a1.5 1.5 0 0 1 3 0v5M17.5 11V9a1.5 1.5 0 0 1 3 0v5c0 4.5-2.5 7-7 7h-1.2a6 6 0 0 1-4.8-2.4L4 14a1.7 1.7 0 0 1 2.6-2.2z"/></>,
    eye: <><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></>,
    "eye-off": <><path d="m3 3 18 18M10.6 6.1A9.6 9.6 0 0 1 12 6c6 0 9.5 6 9.5 6a15 15 0 0 1-2.1 2.8M6.2 6.3A15.5 15.5 0 0 0 2.5 12s3.5 6 9.5 6a9 9 0 0 0 3-.5M9.8 9.8a3 3 0 0 0 4.4 4.4"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    unlock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2"/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
    undo: <><path d="M9 7 4 12l5 5"/><path d="M4 12h9a6 6 0 0 1 6 6"/></>,
    redo: <><path d="m15 7 5 5-5 5"/><path d="M20 12h-9a6 6 0 0 0-6 6"/></>,
    preview: <><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></>,
    close: <><path d="m6 6 12 12M18 6 6 18"/></>,
    "chevron-down": <><path d="m7 9 5 5 5-5"/></>,
    grip: <><circle cx="9" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="9" cy="18" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="18" r="1" fill="currentColor" stroke="none"/></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m4 17 5-5 3 3 2-2 6 5"/></>,
    review: <><path d="M8 4H5a2 2 0 0 0-2 2v14h14v-3"/><path d="M8 2h8v4H8zM8 11h4M8 15h3"/><circle cx="17" cy="12" r="4"/><path d="m20 15 2 2"/></>,
    export: <><path d="M14 3h6v6M20 3l-9 9"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></>,
    profile: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    plan: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8A7 7 0 0 1 18.5 6.5L20 12M4 12l1.5 5.5A7 7 0 0 0 17.9 16"/></>,
    trash: <><path d="M4 7h16M9 3h6l1 4H8zM7 7l1 14h8l1-14M10 11v6M14 11v6"/></>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
    edit: <><path d="m4 16-.8 4.8L8 20l11-11-4-4zM13.5 6.5l4 4"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  };
  return <svg {...common} {...props}>{paths[name]}</svg>;
}

export function IconButton({ label, icon, className = "", ...props }: { label: string; icon: IconName; className?: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className={`icon-button ${className}`.trim()} aria-label={label} title={label} {...props}><Icon name={icon} /></button>;
}
