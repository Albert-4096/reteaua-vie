// `?case=16dec|e3|mocioni` picks a prepared case; `?closure=<id>` opens any closure.
import { api, type CaseSummary } from "../api/client";
import { useResource } from "./store";

export function useCases() {
  return useResource<CaseSummary[]>("cases", () => api.cases());
}

export function useCase(params: URLSearchParams): { caseKey: string | null; closureId: string | null; loading: boolean } {
  const cases = useCases();
  const caseKey = params.get("case");
  const direct = params.get("closure");
  if (direct) return { caseKey: null, closureId: direct, loading: false };
  if (!caseKey) return { caseKey: null, closureId: null, loading: false };
  const hit = cases.data?.find((c) => c.id === `case_${caseKey}` || c.id === caseKey);
  return { caseKey, closureId: hit?.closureId ?? null, loading: cases.loading };
}
