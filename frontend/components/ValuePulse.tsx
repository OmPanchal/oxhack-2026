"use client";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/** Outline only when an existing value changes; never tint the surface. */
export function ValuePulse({ value, children }: { value: string | number; children: ReactNode }) {
  const element = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  useEffect(() => {
    if (previous.current !== value && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const animation = element.current?.animate([
        { outline: "1px solid var(--silver)", outlineOffset: "3px" },
        { outline: "1px solid transparent", outlineOffset: "3px" },
      ], { duration: 650, easing: "ease-out" });
      previous.current = value;
      return () => animation?.cancel();
    }
    previous.current = value;
  }, [value]);
  return <span ref={element}>{children}</span>;
}
