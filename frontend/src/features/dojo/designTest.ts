import type { DesignTest } from "../pipelines/designTest";
import { useDojoAccess } from "./access";
import { HistoryTestPanel, HistoryTestStatus } from "./HistoryTest";
import { HistoryTestValues } from "./HistoryTestValues";

const HISTORY_TEST: DesignTest = { Panel: HistoryTestPanel, Status: HistoryTestStatus, Values: HistoryTestValues };

/** The composer's test on recorded values, for members who may use the Dojo. */
export function useDesignTest() {
  return useDojoAccess() ? HISTORY_TEST : undefined;
}
