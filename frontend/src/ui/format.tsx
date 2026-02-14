import React from "react";

export function Money({ value }: { value: number }) {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  return <span>{sign}${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>;
}

export function Percent({ value }: { value: number }) {
  return <span>{(value * 100).toFixed(1)}%</span>;
}

