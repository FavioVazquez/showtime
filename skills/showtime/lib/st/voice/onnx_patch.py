"""Load-time fix for half-precision Kokoro exports (stdlib only, no `onnx` package).

The fp16 Kokoro export computes the source phase as atan(imag / real). In half
precision both parts of a quiet STFT bin can round to exactly 0, and 0/0 gives
NaN, which then spreads through the vocoder and silences the whole batch (seen
with some voice + text pairs). PyTorch's atan2(0, 0) is 0, so the fix replaces
NaN quotients that feed an Atan with 0:

    q = Div(a, b)  ->  Atan(q)
becomes
    q = Div(a, b);  z = CastLike(0.0, q);  n = IsNaN(q);  s = Where(n, z, q)  ->  Atan(s)

The downloaded file is never modified (it stays sha256-verifiable): `guard_nan_atan`
rewrites the serialized ModelProto in memory and onnxruntime loads the bytes.
A model without the pattern (the fp32 exports) comes back unchanged.

Only the protobuf wire format is needed: ModelProto.graph = field 7,
GraphProto.node = 1, NodeProto input = 1, output = 2, name = 3, op_type = 4,
attribute = 5; AttributeProto name = 1, t = 5, type = 20; TensorProto
data_type = 2, raw_data = 9.
"""
from __future__ import annotations

import struct
from typing import Dict, Iterator, List, Optional, Tuple

_SUFFIX = "_st_nanguard"


def _varint(buf: bytes, pos: int) -> Tuple[int, int]:
    out = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        out |= (b & 0x7F) << shift
        if b < 0x80:
            return out, pos
        shift += 7


def _enc_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _fields(buf: bytes, start: int = 0, end: Optional[int] = None) -> Iterator[Tuple[int, int, int, int, int]]:
    """(field, wire type, payload start, payload end, field start) for each top-level field."""
    pos, end = start, len(buf) if end is None else end
    while pos < end:
        fstart = pos
        tag, pos = _varint(buf, pos)
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            _, pos2 = _varint(buf, pos)
            yield field, wt, pos, pos2, fstart
            pos = pos2
        elif wt == 1:
            yield field, wt, pos, pos + 8, fstart
            pos += 8
        elif wt == 2:
            n, pos = _varint(buf, pos)
            yield field, wt, pos, pos + n, fstart
            pos += n
        elif wt == 5:
            yield field, wt, pos, pos + 4, fstart
            pos += 4
        else:
            raise ValueError("unsupported protobuf wire type %d" % wt)


def _ld(field: int, payload: bytes) -> bytes:
    return _enc_varint((field << 3) | 2) + _enc_varint(len(payload)) + payload


def _node_info(buf: bytes, start: int, end: int) -> Dict[str, object]:
    info: Dict[str, object] = {"input": [], "output": [], "name": "", "op_type": ""}
    for f, wt, a, b, _ in _fields(buf, start, end):
        if wt != 2:
            continue
        if f == 1:
            info["input"].append(buf[a:b].decode("utf-8"))  # type: ignore[union-attr]
        elif f == 2:
            info["output"].append(buf[a:b].decode("utf-8"))  # type: ignore[union-attr]
        elif f == 3:
            info["name"] = buf[a:b].decode("utf-8")
        elif f == 4:
            info["op_type"] = buf[a:b].decode("utf-8")
    return info


def _node(op: str, inputs: List[str], outputs: List[str], name: str, attrs: bytes = b"") -> bytes:
    body = b"".join(_ld(1, i.encode()) for i in inputs) + b"".join(_ld(2, o.encode()) for o in outputs)
    body += _ld(3, name.encode()) + _ld(4, op.encode()) + attrs
    return body


def _zero_const_attr() -> bytes:
    tensor = _enc_varint((2 << 3) | 0) + _enc_varint(1)            # data_type = FLOAT (1), scalar
    tensor += _ld(9, struct.pack("<f", 0.0))                       # raw_data
    attr = _ld(1, b"value") + _ld(5, tensor) + _enc_varint((20 << 3) | 0) + _enc_varint(4)  # type = TENSOR
    return _ld(5, attr)


def _rewrite_inputs(buf: bytes, start: int, end: int, old: str, new: str) -> bytes:
    out = bytearray()
    for f, wt, a, b, fs in _fields(buf, start, end):
        if f == 1 and wt == 2 and buf[a:b].decode("utf-8") == old:
            out += _ld(1, new.encode())
        else:
            out += buf[fs:b]
    return bytes(out)


def guard_nan_atan(model: bytes) -> Tuple[bytes, int]:
    """(patched model bytes, number of Atan inputs guarded). Idempotent."""
    graph_span = None
    for f, wt, a, b, fs in _fields(model):
        if f == 7 and wt == 2:
            graph_span = (fs, a, b)
    if graph_span is None:
        return model, 0
    gfs, ga, gb = graph_span
    nodes = []            # (field start, payload start, payload end, info)
    for f, wt, a, b, fs in _fields(model, ga, gb):
        if f == 1 and wt == 2:
            nodes.append((fs, a, b, _node_info(model, a, b)))
    producers = {o: n[3] for n in nodes for o in n[3]["output"]}  # type: ignore[union-attr]
    outputs = {o for n in nodes for o in n[3]["output"]}  # type: ignore[union-attr]
    targets = {}
    for _, _, _, info in nodes:
        if info["op_type"] != "Atan" or not info["input"]:
            continue
        src = info["input"][0]  # type: ignore[index]
        prod = producers.get(src)
        if prod is None or prod["op_type"] != "Div" or (src + _SUFFIX) in outputs:
            continue
        targets[src] = src + _SUFFIX
    if not targets:
        return model, 0
    new_graph = bytearray()
    node_ends = {n[0]: n for n in nodes}
    pos = ga
    for f, wt, a, b, fs in _fields(model, ga, gb):
        if fs in node_ends:
            info = node_ends[fs][3]
            ins = info["input"]
            hit = [i for i in ins if i in targets] if info["op_type"] == "Atan" else []  # type: ignore[union-attr]
            if hit:
                payload = _rewrite_inputs(model, a, b, hit[0], targets[hit[0]])
                new_graph += _ld(1, payload)
            else:
                new_graph += model[fs:b]
            for o in info["output"]:  # type: ignore[union-attr]
                if o in targets:
                    s = targets[o]
                    z, n = s + "_zero32", s + "_isnan"
                    new_graph += _ld(1, _node("Constant", [], [z], z, _zero_const_attr()))
                    new_graph += _ld(1, _node("CastLike", [z, o], [z + "_like"], z + "_like"))
                    new_graph += _ld(1, _node("IsNaN", [o], [n], n))
                    new_graph += _ld(1, _node("Where", [n, z + "_like", o], [s], s))
        else:
            new_graph += model[fs:b]
        pos = b
    assert pos == gb
    out = bytearray(model[:gfs])
    out += _ld(7, bytes(new_graph))
    out += model[gb:]
    return bytes(out), len(targets)
