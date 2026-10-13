// The X-ray's beats, in seconds (`showtime new xray --duration` and `showtime retime` scale them). The clip itself
// is never retimed: it starts at 0 and its events land on their own frames. Set endcard to the clip's length.
var CUE = {
  duration: 12.8,
  scan: 0.3,
  scan_end: 1.3,
  labels: 1.5,
  endcard: 9.4,
};
