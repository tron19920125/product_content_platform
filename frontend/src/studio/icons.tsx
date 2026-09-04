import type {CSSProperties} from "react";
const paths: Record<string, string> = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  detail: "M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5",
  image: "M3 4h18v16H3z M3 16l6-6 5 5 3-3 4 4 M16 8h.01",
  scene: "M3 20l7-12 4 6 3-4 4 10H3z M16 4h.01",
  spark: "m12 2 2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8L12 2z",
  folder: "M3 6h7l2 2h9v12H3z M3 6V4h7l2 2",
  history: "M3 12a9 9 0 1 0 3-6 M3 3v6h6 M12 7v5l3 2",
  plus: "M12 4v16 M4 12h16", close: "M5 5l14 14 M19 5 5 19",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6",
  download: "M12 3v13 M7 11l5 5 5-5 M4 17v4h16v-4",
  arrow: "M5 12h14 M13 6l6 6-6 6", back: "M19 12H5 M11 6l-6 6 6 6",
  check: "M4 12l5 5L20 6", edit: "m4 16 12-12 4 4L8 20H4v-4z M14 6l4 4",
  trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
  search: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14z M15 15l6 6",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 10v7 M12 6v.01",
  text: "M4 4h16 M12 4v16 M8 20h8", undo: "M8 4 3 9l5 5 M3 9h11a6 6 0 0 1 0 12",
  redo: "m16 4 5 5-5 5 M21 9H10a6 6 0 0 0 0 12", lock: "M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0v4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  layers: "m12 3 10 6-10 6L2 9l10-6z M2 13l10 6 10-6 M2 17l10 6 10-6",
  chevron: "m9 5 7 7-7 7", stop: "M5 5h14v14H5z", copy: "M8 8h13v13H8z M16 8V3H3v13h5",
};
export function Icon({name, size = 20, style}: {name: string; size?: number; style?: CSSProperties}) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" style={style}><path d={paths[name] ?? paths.image}/></svg>;
}
