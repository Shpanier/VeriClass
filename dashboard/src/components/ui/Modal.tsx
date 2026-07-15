import type { ReactNode } from "react";

// The fixed full-screen overlay shell shared by every dashboard modal: click the
// backdrop to close, click the panel to keep it open. Extracted from the
// identical inline copies in AskThemModal / ChatViewModal / ProctorLogModal.
export function Modal({
  onClose,
  width = 720,
  children,
}: {
  onClose: () => void;
  width?: number;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "grid",
        placeItems: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          padding: 24,
          borderRadius: 8,
          width,
          maxWidth: "92vw",
          maxHeight: "85vh",
          overflow: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
