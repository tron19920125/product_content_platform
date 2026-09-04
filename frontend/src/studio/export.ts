import {renderComposition} from "./editor";
import type {Version} from "./types";

export type ImageFormat = "png" | "jpg";

async function versionCanvas(version: Version): Promise<HTMLCanvasElement> {
  const canvas = document.createElement("canvas");
  await renderComposition(canvas, version.base_url, version.layers);
  return canvas;
}

async function canvasBlob(canvas: HTMLCanvasElement, format: ImageFormat, quality = .94): Promise<Blob> {
  if (format === "jpg") {
    const flattened = document.createElement("canvas");
    flattened.width = canvas.width; flattened.height = canvas.height;
    const context = flattened.getContext("2d")!;
    context.fillStyle = "#fff"; context.fillRect(0, 0, flattened.width, flattened.height);
    context.drawImage(canvas, 0, 0);
    canvas = flattened;
  }
  return new Promise((resolve, reject) => canvas.toBlob(
    value => value ? resolve(value) : reject(new Error("图片导出失败")),
    format === "png" ? "image/png" : "image/jpeg", quality,
  ));
}

export function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 3000);
}

export async function downloadVersion(version: Version, filename: string, format: ImageFormat) {
  downloadBlob(await canvasBlob(await versionCanvas(version), format), `${filename}.${format}`);
}

export async function downloadZip(rows: {version: Version; filename: string}[]) {
  if (!rows.length) throw new Error("当前没有可导出的图片");
  const files: {name: string; data: Uint8Array}[] = [];
  for (const row of rows) {
    const blob = await canvasBlob(await versionCanvas(row.version), "png");
    files.push({name: `${row.filename}.png`, data: new Uint8Array(await blob.arrayBuffer())});
  }
  downloadBlob(new Blob([zipStore(files) as BlobPart], {type: "application/zip"}), "商品内容套图.zip");
}

export async function downloadLongImage(rows: {version: Version; filename: string}[], targetWidth = 2048) {
  if (!rows.length) throw new Error("当前没有可拼接的图片");
  const sources = await Promise.all(rows.map(row => versionCanvas(row.version)));
  const heights = sources.map(canvas => Math.round(canvas.height * targetWidth / canvas.width));
  const totalHeight = heights.reduce((sum, value) => sum + value, 0);
  if (targetWidth * totalHeight > 80_000_000 || totalHeight > 32767) {
    throw new Error("长图尺寸过大，为避免浏览器内存不足，请改用 ZIP 下载");
  }
  const result = document.createElement("canvas"); result.width = targetWidth; result.height = totalHeight;
  const context = result.getContext("2d")!; context.fillStyle = "#fff"; context.fillRect(0, 0, result.width, result.height);
  let y = 0;
  sources.forEach((canvas, index) => {context.drawImage(canvas, 0, y, targetWidth, heights[index]); y += heights[index];});
  downloadBlob(await canvasBlob(result, "png"), `商品详情长图-${targetWidth}px.png`);
}

function zipStore(files: {name: string; data: Uint8Array}[]): Uint8Array {
  const encoder = new TextEncoder();
  const chunks: Uint8Array[] = [], central: Uint8Array[] = [];
  let offset = 0;
  for (const file of files) {
    const name = encoder.encode(file.name), crc = crc32(file.data);
    const local = record(30 + name.length + file.data.length);
    write(local, 0, 0x04034b50, 4); write(local, 4, 20, 2); write(local, 6, 0x800, 2);
    write(local, 14, crc, 4); write(local, 18, file.data.length, 4); write(local, 22, file.data.length, 4);
    write(local, 26, name.length, 2); local.set(name, 30); local.set(file.data, 30 + name.length); chunks.push(local);
    const header = record(46 + name.length);
    write(header, 0, 0x02014b50, 4); write(header, 4, 20, 2); write(header, 6, 20, 2); write(header, 8, 0x800, 2);
    write(header, 16, crc, 4); write(header, 20, file.data.length, 4); write(header, 24, file.data.length, 4);
    write(header, 28, name.length, 2); write(header, 42, offset, 4); header.set(name, 46); central.push(header);
    offset += local.length;
  }
  const centralSize = central.reduce((sum, value) => sum + value.length, 0), end = record(22);
  write(end, 0, 0x06054b50, 4); write(end, 8, files.length, 2); write(end, 10, files.length, 2);
  write(end, 12, centralSize, 4); write(end, 16, offset, 4);
  return concat([...chunks, ...central, end]);
}

function record(length: number) {return new Uint8Array(length);}
function write(target: Uint8Array, offset: number, value: number, bytes: number) {
  const view = new DataView(target.buffer, target.byteOffset, target.byteLength);
  if (bytes === 2) view.setUint16(offset, value, true); else view.setUint32(offset, value >>> 0, true);
}
function concat(chunks: Uint8Array[]) {
  const output = new Uint8Array(chunks.reduce((sum, value) => sum + value.length, 0));
  let offset = 0; for (const chunk of chunks) {output.set(chunk, offset); offset += chunk.length;} return output;
}
function crc32(data: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of data) {crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));}
  return (crc ^ 0xffffffff) >>> 0;
}
