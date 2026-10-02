#!/usr/bin/env python3
"""olcrtc-yaml2uri: parse olcrtc YAML config(s) and emit olcrtc:// share links.

Input is a normal olcrtc client config (docs/configuration.md): mode: cnc/srv,
auth.provider, room.id, crypto.key (or crypto.key_file), net.transport and
optional vp8.* / sei.* / video.* parameter sections. Failover configs with
profiles[] yield one link per profile.

The payload is rendered per docs/uri.md: `<key=value&key=value>` placed right
after the transport name, dropped when the transport needs no parameters
(datachannel) or when all values equal the documented defaults (in that case
no payload is emitted anyway unless --no-defaults-detection is passed).
`data:` is never encoded (local runtime setting). The `$MIMO` tail is
client-only UI metadata, supplied via --comment.

Usage:
    python3 olcrtc_yaml2uri.py client.yaml                 # single config
    python3 olcrtc_yaml2uri.py failover.yaml               # one link per profile
    python3 olcrtc_yaml2uri.py *.yaml --comment "RU sub"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("нужен PyYAML: pip install pyyaml")

SEPARATORS = "?<>@#$"
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

# URI key -> (YAML section, YAML key, default) per docs/uri.md payload tables.
PAYLOAD_FIELDS = {
    "vp8channel": [
        ("vp8-fps", "vp8", "fps"),
        ("vp8-batch", "vp8", "batch_size"),
    ],
    "seichannel": [
        ("fps", "sei", "fps"),
        ("batch", "sei", "batch_size"),
        ("frag", "sei", "fragment_size"),
        ("ack-ms", "sei", "ack_timeout_ms"),
    ],
    "videochannel": [
        ("video-w", "video", "width"),
        ("video-h", "video", "height"),
        ("video-fps", "video", "fps"),
        ("video-codec", "video", "codec"),
        ("video-qr-size", "video", "qr_size"),
        ("video-qr-recovery", "video", "qr_recovery"),
        ("video-tile-module", "video", "tile_module"),
        ("video-tile-rs", "video", "tile_rs"),
    ],
    # datachannel: no payload
}


def _check_field(value: str, what: str) -> str:
    if not value:
        raise ValueError(f"{what}: пустое значение")
    bad = [c for c in SEPARATORS if c in value]
    if bad:
        raise ValueError(f"{what}: недопустимые символы-разделители {bad}")
    return value


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("корень YAML должен быть словарём")
    return data


def _resolve_key(cfg: dict, base: Path) -> str:
    if "key" in cfg.get("crypto", {}) and "key_file" in cfg.get("crypto", {}):
        raise ValueError("crypto.key и crypto.key_file заданы одновременно")
    key = cfg.get("crypto", {}).get("key")
    if key is None:
        key_file = cfg.get("crypto", {}).get("key_file")
        if not key_file:
            raise ValueError("не задан crypto.key / crypto.key_file")
        pf = Path(key_file)
        key = (pf if pf.is_absolute() else base / pf).read_text(encoding="utf-8").strip()
    key = str(key).strip()
    if not HEX64.match(key):
        raise ValueError("crypto.key: должен быть 64 hex-символа (32 байта)")
    return key


def cfg_to_uri(cfg: dict, base: Path, comment: str = "") -> str:
    if str(cfg.get("mode", "")) == "gen":
        raise ValueError("mode: gen не транслируется в olcrtc:// ссылку")
    provider = _check_field(str(cfg.get("auth", {}).get("provider", "")), "auth.provider")
    transport = _check_field(str(cfg.get("net", {}).get("transport", "")), "net.transport")
    room = _check_field(str(cfg.get("room", {}).get("id", "")), "room.id")
    key = _resolve_key(cfg, base)

    payload = ""
    for uri_key, section, yaml_key in PAYLOAD_FIELDS.get(transport, []):
        value = cfg.get(section, {}).get(yaml_key)
        if value is not None:
            value = str(value)
            _check_field(value, f"{section}.{yaml_key}")
            payload += ("" if not payload else "&") + f"{uri_key}={value}"

    comment_part = ""
    if comment:
        comment_part = "$" + comment

    return (
        f"olcrtc://{provider}?{transport}"
        + (f"<{payload}>" if payload else "")
        + f"@{room}#{key}{comment_part}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("yaml_files", nargs="+")
    ap.add_argument("--comment", default="", help="хвост $MIMO (метаданные для UI)")
    args = ap.parse_args()

    exit_code = 0
    for arg in args.yaml_files:
        path = Path(arg)
        try:
            cfg = _load(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            print(f"{path}: не читается: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        profiles = cfg.get("profiles")
        if isinstance(profiles, list) and profiles:
            entries = [(f"profile[{i}]", p) for i, p in enumerate(profiles)]
        else:
            entries = [("", cfg)]

        for label, p in entries:
            try:
                uri = cfg_to_uri(p, path.resolve().parent, args.comment)
                print(f"{label}: {uri}" if label else uri)
            except (ValueError, OSError) as exc:
                print(f"{path} {label}: ошибка: {exc}", file=sys.stderr)
                exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()