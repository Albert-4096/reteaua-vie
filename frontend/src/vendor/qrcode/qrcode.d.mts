// Types for the vendored qrcode-generator 2.0.4 (MIT, Kazuhiko Arase; licence header in qrcode.mjs).
// Vendored as one file instead of a package, so the shared node_modules stays untouched.
export interface QRCode {
  addData(data: string, mode?: "Numeric" | "Alphanumeric" | "Byte" | "Kanji"): void;
  make(): void;
  getModuleCount(): number;
  isDark(row: number, col: number): boolean;
}
declare const qrcode: (typeNumber: number, errorCorrectionLevel: "L" | "M" | "Q" | "H") => QRCode;
export default qrcode;
