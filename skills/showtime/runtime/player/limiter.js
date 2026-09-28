/* showtime export: gain + look-ahead peak limiter for the live score (--audio score).
 * The exporter runs this same function on the offline score to choose the gain, and the player runs
 * it in the browser on the score it renders, so the HTML plays at the loudness the MP4 has.
 * stLimit(channels: Float32Array[], sampleRate, gainDb, ceilingDb) -> new Float32Array[]
 */
(function (root) {
  'use strict';
  function stLimit(chs, sr, gainDb, ceilDb) {
    var n = chs[0].length, nc = chs.length;
    var g = Math.pow(10, (gainDb || 0) / 20), ceil = Math.pow(10, (ceilDb === undefined ? -1 : ceilDb) / 20);
    var la = Math.max(1, Math.round(0.005 * sr));          // 5 ms look-ahead
    var att = Math.exp(-1 / (0.4 * la)), rel = Math.exp(-1 / (0.12 * sr));
    var req = new Float32Array(n);
    for (var i = 0; i < n; i++) {
      var pk = 0;
      for (var c = 0; c < nc; c++) { var a = chs[c][i] < 0 ? -chs[c][i] : chs[c][i]; if (a > pk) pk = a; }
      pk *= g;
      req[i] = pk > ceil ? ceil / pk : 1;
    }
    // minimum of the required gain over [i, i + la] (monotonic deque)
    var win = new Float32Array(n), dq = new Int32Array(n), h = 0, t = 0, j = 0;
    for (i = 0; i < n; i++) {
      var end = Math.min(n - 1, i + la);
      for (; j <= end; j++) { while (t > h && req[dq[t - 1]] >= req[j]) t--; dq[t++] = j; }
      while (dq[h] < i) h++;
      win[i] = req[dq[h]];
    }
    var out = [], cur = 1, env = new Float32Array(n);
    for (i = 0; i < n; i++) {
      var target = win[i];
      cur = target < cur ? target + (cur - target) * att : target + (cur - target) * rel;
      if (cur > target && cur - target < 1e-6) cur = target;
      env[i] = cur;
    }
    for (c = 0; c < nc; c++) {
      var src = chs[c], dst = new Float32Array(n);
      for (i = 0; i < n; i++) {
        var x = src[i] * g * env[i];
        dst[i] = x > ceil ? ceil : x < -ceil ? -ceil : x;
      }
      out.push(dst);
    }
    return out;
  }
  root.__stLimit = stLimit;
})(typeof window !== 'undefined' ? window : globalThis);
