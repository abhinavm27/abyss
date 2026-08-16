import { afterEach, describe, expect, it, vi } from "vitest";
import { api, setToken } from "./api";

const ok = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "content-type": "application/json" },
});

describe("report-intake API contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setToken(null);
  });

  it("prepares a referral without adding processing consent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ source_hash: "sha256:abc" }));
    vi.stubGlobal("fetch", fetchMock);
    setToken("synthetic-token");

    await api.prepareReportIntake(new File(["synthetic referral"], "referral.txt", { type: "text/plain" }));

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = init.body as FormData;
    expect(path).toBe("/api/report-intake/prepare");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ authorization: "Bearer synthetic-token" });
    expect(body.get("file")).toBeInstanceOf(File);
    expect(body.has("consent_scope")).toBe(false);
    expect(body.has("consent_approved")).toBe(false);
  });

  it("analyzes only with the exact prepared scope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ analysis_id: "analysis-1", orders: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await api.analyzeReportIntake(
      new File(["synthetic referral"], "referral.txt", { type: "text/plain" }),
      "process doctor report sha256:abc",
      "journey-1",
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = init.body as FormData;
    expect(body.get("consent_scope")).toBe("process doctor report sha256:abc");
    expect(body.get("consent_approved")).toBe("true");
    expect(body.get("journey_id")).toBe("journey-1");
  });

  it("confirms only the explicitly selected candidate IDs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ options_ready: false, journey: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await api.confirmReportOrders("analysis-1", ["order-2"], "journey-1");

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/report-intake/analysis-1/confirm");
    expect(JSON.parse(String(init.body))).toEqual({
      order_ids: ["order-2"],
      journey_id: "journey-1",
    });
  });
});
