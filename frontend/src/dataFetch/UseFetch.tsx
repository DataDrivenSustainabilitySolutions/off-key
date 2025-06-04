import { useContext } from "react";
import { FetchContext } from "../dataFetch/FetchContext"; // Pfad anpassen!
import type { FetchContextType } from "../dataFetch/FetchContext";

export const useFetch = (): FetchContextType => {
  const context = useContext(FetchContext);
  if (!context) {
    throw new Error("useFetch muss innerhalb eines FetchProvider verwendet werden");
  }
  return context;
};
