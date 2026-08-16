import { describe, expect, it } from "vitest";
import { voiceStartErrorMessage } from "./voiceErrors";

const secureEnvironment = { isSecureContext: true, hasGetUserMedia: true };

describe("voiceStartErrorMessage", () => {
  it("identifies an insecure HTTP origin before blaming the microphone", () => {
    expect(voiceStartErrorMessage(new TypeError("undefined"), {
      isSecureContext: false,
      hasGetUserMedia: false,
      secureAppUrl: "https://vela.example",
    })).toContain("https://vela.example");
  });

  it("gives a permission-specific recovery step", () => {
    const error = new DOMException("denied", "NotAllowedError");
    expect(voiceStartErrorMessage(error, secureEnvironment)).toContain("address bar");
  });

  it("does not report a gateway failure as a missing microphone", () => {
    const message = voiceStartErrorMessage(new Error("voice connect timed out"), secureEnvironment);
    expect(message).toContain("voice service");
    expect(message).not.toContain("No microphone");
  });
});
