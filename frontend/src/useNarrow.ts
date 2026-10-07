import { useEffect, useState } from "react";

export function useNarrowViewport(maxWidth = 480) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function")
      return;
    const query = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const apply = () => setNarrow(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, [maxWidth]);
  return narrow;
}
