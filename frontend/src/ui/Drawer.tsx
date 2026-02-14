import React from "react";

export function Drawer({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;

  return (
    <div className="drawerOverlay" role="dialog" aria-modal="true">
      <button className="drawerBackdrop" onClick={onClose} aria-label="Close" />
      <div className="drawerPanel">
        <div className="drawerHeader">
          <div className="drawerTitle">{title}</div>
          <button className="drawerClose" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="drawerBody">{children}</div>
      </div>
    </div>
  );
}

