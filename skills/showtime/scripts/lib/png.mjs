// PNG chunk helpers. A still decoded from a BT.709 video carries cICP/cHRM/gAMA colour chunks; a
// browser honours them and draws the still visibly darker than the same frame playing in <video>.
// Dropping them leaves plain (sRGB-assumed) pixels, exactly the values the video shows.

const SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Colour-management chunks removed by stripColorChunks. */
export const COLOR_CHUNKS = new Set(['cICP', 'cHRM', 'gAMA', 'iCCP', 'sRGB']);

/** Chunk types of a PNG, in order (for tests and diagnostics). */
export function pngChunks(buf) {
  const out = [];
  if (!Buffer.isBuffer(buf) || buf.length < 8 || !buf.subarray(0, 8).equals(SIG)) return out;
  for (let i = 8; i + 12 <= buf.length;) {
    const n = buf.readUInt32BE(i);
    out.push(buf.toString('latin1', i + 4, i + 8));
    i += 12 + n;
  }
  return out;
}

/** The PNG without its colour chunks; other chunks are copied byte for byte (CRCs intact). Non-PNG input is returned as is. */
export function stripColorChunks(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 8 || !buf.subarray(0, 8).equals(SIG)) return buf;
  const keep = [buf.subarray(0, 8)];
  let dropped = false;
  for (let i = 8; i + 12 <= buf.length;) {
    const n = buf.readUInt32BE(i);
    const end = i + 12 + n;
    if (end > buf.length) { keep.push(buf.subarray(i)); break; }
    if (COLOR_CHUNKS.has(buf.toString('latin1', i + 4, i + 8))) dropped = true;
    else keep.push(buf.subarray(i, end));
    i = end;
  }
  return dropped ? Buffer.concat(keep) : buf;
}
