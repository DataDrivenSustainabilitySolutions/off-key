import { useContext } from "react";
import { FetchContext } from "../dataFetch/FetchContext";
import type { FetchContextType } from "../dataFetch/FetchContext";

export const useFetch = (): FetchContextType => {
  const context = useContext(FetchContext);
  if (!context) {
    throw new Error(
      "The useFetch hook must be used within a FetchProvider component."
    );
  }
  return context;
};
