import {useEffect, useRef} from "react";
import type {ReactNode} from "react";
import {Icon} from "./icons";

// Only the top dialog handles focus and Escape when a confirmation is stacked.
const dialogs: HTMLElement[] = [];
export function Modal({title, children, onClose, wide = false, busy = false}: {title: string; children: ReactNode; onClose: () => void; wide?: boolean; busy?: boolean}) {
  const panel = useRef<HTMLElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);
  const close = useRef(onClose);
  const pending = useRef(busy);
  close.current = onClose;
  pending.current = busy;
  useEffect(() => {
    const element = panel.current!;
    const previous = opener.current;
    dialogs.push(element);
    const focusable = () => Array.from(element.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')).filter(item => item.getClientRects().length);
    if (!element.contains(document.activeElement)) (focusable()[0] ?? element).focus({preventScroll: true});
    const onKey = (event: KeyboardEvent) => {
      if (dialogs.at(-1) !== element) return;
      if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); if (!pending.current) close.current();}
      if (event.key === "Tab") {
        const items = focusable();
        const index = items.indexOf(document.activeElement as HTMLElement);
        if (!items.length) {event.preventDefault(); element.focus();}
        else if (event.shiftKey && index <= 0) {event.preventDefault(); items.at(-1)!.focus();}
        else if (!event.shiftKey && (index < 0 || index === items.length - 1)) {event.preventDefault(); items[0].focus();}
      }
    };
    const onFocus = (event: FocusEvent) => {if (dialogs.at(-1) === element && !element.contains(event.target as Node)) (focusable()[0] ?? element).focus();};
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("focusin", onFocus);
    return () => {
      dialogs.splice(dialogs.indexOf(element), 1);
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("focusin", onFocus);
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return <div className="st-overlay" onMouseDown={event => {if (!busy && event.target === event.currentTarget) onClose();}}><section ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} aria-busy={busy} className={`st-modal ${wide ? "wide" : ""}`}><header><h2>{title}</h2><button className="st-icon" aria-label="关闭" disabled={busy} onClick={onClose}><Icon name="close"/></button></header>{children}</section></div>;
}
