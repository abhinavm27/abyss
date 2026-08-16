import { Capacitor } from "@capacitor/core";

/** Capture an insurance card and hand back the bytes.
 *
 * Two paths, because ABYSS runs in both places: the native camera under
 * Capacitor, and a plain file input in the browser. The web path accepts a
 * photo from the library too — on a laptop there is no card to point a camera
 * at, and refusing the upload would make the feature untestable outside iOS. */
export async function captureCard(): Promise<File | null> {
  if (Capacitor.isNativePlatform()) {
    const { Camera, CameraResultType, CameraSource } = await import("@capacitor/camera");
    const photo = await Camera.getPhoto({
      quality: 80,
      // The model reads printed text, so a full-resolution image buys nothing
      // and costs upload time on a phone connection.
      width: 1600,
      resultType: CameraResultType.Base64,
      source: CameraSource.Prompt,
      correctOrientation: true,
    });
    if (!photo.base64String) return null;
    const bytes = Uint8Array.from(atob(photo.base64String), (c) => c.charCodeAt(0));
    return new File([bytes], `card.${photo.format || "jpeg"}`, {
      type: `image/${photo.format || "jpeg"}`,
    });
  }

  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    // Hints a phone browser toward the camera; ignored on desktop, which falls
    // back to the file picker.
    input.capture = "environment";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.oncancel = () => resolve(null);
    input.click();
  });
}

/** OCR stays in the browser so printed member identifiers are not sent to a
 * hosted vision model. The authenticated API receives the image and recognized
 * text together, then deterministically validates labeled card fields. */
export async function extractCardText(file: File): Promise<string> {
  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker("eng");
  try {
    const result = await worker.recognize(file);
    return result.data.text.trim();
  } finally {
    await worker.terminate();
  }
}
