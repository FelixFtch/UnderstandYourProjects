// Data source for Receipts: companion-api /api/studio/receipts, or fixtures.
import { api } from "../../api/client";
import type { ReceiptsQuery, StudioReceiptList } from "../../api/contracts";

const FIXTURES = import.meta.env.VITE_STUDIO_FIXTURES === "true";
const fx = () => import("./fixtures");

export const receiptsData = {
  list: (opts: ReceiptsQuery = {}, signal?: AbortSignal): Promise<StudioReceiptList> =>
    (FIXTURES ? fx().then((f) => f.receiptsList(opts)) : api.receipts(opts, signal)),
};
