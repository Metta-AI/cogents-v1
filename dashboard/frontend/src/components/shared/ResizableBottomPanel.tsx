"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import type { ReactNode } from "react";

interface ResizableBottomPanelProps {
  children: ReactNode;
  defaultHeight?: number; // px, default 40vh equivalent
  minHeight?: number;
  maxHeight?: number;
  className?: string;
}

export function ResizableBottomPanel({
  children,
  defaultHeight,
  minHeight = 120,
  maxHeight,
  className = "",
}: ResizableBottomPanelProps) {
  const [height, setHeight] = useState<number>(() => defaultHeight ?? Math.round(window.innerHeight * 0.4));
  const dragging = useRef(false);
  const startY = useRef(0);
  const startH = useRef(0);

  const effectiveMax = maxHeight ?? Math.round(window.innerHeight * 0.8);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startY.current = e.clientY;
    startH.current = height;
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  }, [height]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const delta = startY.current - e.clientY;
      const newH = Math.max(minHeight, Math.min(effectiveMax, startH.current + delta));
      setHeight(newH);
    };
    const onMouseUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [minHeight, effectiveMax]);

  return (
    <div
      className={`fixed flex flex-col border-t ${className}`}
      style={{
        left: "var(--sidebar-w)",
        right: 0,
        bottom: 0,
        height: `${height}px`,
        borderColor: "var(--border)",
        background: "var(--bg-deep)",
        zIndex: 20,
      }}
    >
      {/* Drag handle */}
      <div
        onMouseDown={onMouseDown}
        style={{
          height: "5px",
          cursor: "row-resize",
          flexShrink: 0,
          background: "transparent",
          position: "relative",
          marginTop: "-2px",
          zIndex: 1,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.background = "var(--accent)";
          (e.currentTarget as HTMLElement).style.opacity = "0.4";
        }}
        onMouseLeave={(e) => {
          if (!dragging.current) {
            (e.currentTarget as HTMLElement).style.background = "transparent";
            (e.currentTarget as HTMLElement).style.opacity = "1";
          }
        }}
      />
      <div className="flex flex-col flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  );
}
