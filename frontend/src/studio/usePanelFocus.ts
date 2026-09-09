import {useEffect, useRef} from "react";
import type {RefObject} from "react";

/** Keep keyboard navigation in an open drawer and return to its trigger. */
export function usePanelFocus(panel: RefObject<HTMLElement | null>, open: boolean, onClose: () => void) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open || !panel.current) return;
    const element = panel.current;
    const previous = document.activeElement as HTMLElement | null;
    const items = () => [...element.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(item => item.checkVisibility() && !item.closest('[inert]'));
    items()[0]?.focus({preventScroll:true});
    const keydown = (event: KeyboardEvent) => {
      if (document.querySelector('.st-overlay') || (document.activeElement as HTMLElement)?.closest('[role="menu"]')) return;
      if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); close.current();}
      if (event.key === "Tab") {
        const controls = items();
        const index = controls.indexOf(document.activeElement as HTMLElement);
        if (event.shiftKey && index <= 0) {event.preventDefault(); controls.at(-1)?.focus();}
        else if (!event.shiftKey && (index < 0 || index === controls.length - 1)) {event.preventDefault(); controls[0]?.focus();}
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      // A newly added canvas text field may already have taken focus.
      if (previous?.isConnected && (document.activeElement === document.body || element.contains(document.activeElement))) previous.focus({preventScroll:true});
    };
  }, [open, panel]);
}
