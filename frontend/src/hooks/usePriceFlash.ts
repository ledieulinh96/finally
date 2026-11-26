"use client";

import { useEffect, useRef, useState } from "react";

export const FLASH_MS = 500;

/**
 * Returns "up" | "down" for FLASH_MS after `price` changes, then "".
 * The first observed price never flashes.
 */
export function usePriceFlash(price: number | null | undefined): "up" | "down" | "" {
  const prev = useRef<number | null | undefined>(price);
  const [flash, setFlash] = useState<"up" | "down" | "">("");

  useEffect(() => {
    const before = prev.current;
    prev.current = price;
    if (before === null || before === undefined || price === null || price === undefined) return;
    if (price === before) return;
    setFlash(price > before ? "up" : "down");
    const id = window.setTimeout(() => setFlash(""), FLASH_MS);
    return () => window.clearTimeout(id);
  }, [price]);

  return flash;
}
