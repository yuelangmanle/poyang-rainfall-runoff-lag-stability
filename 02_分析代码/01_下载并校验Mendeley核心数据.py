#!/usr/bin/env python3
"""下载并校验 Mendeley Data v1 中的 14 个降水/流量核心文件。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DATASET_ID = "59bttt5pbj"
VERSION = "1"
DOI = "10.17632/59bttt5pbj.1"
LICENSE = "CC BY 4.0"
FILES_API = f"https://data.mendeley.com/api/datasets/{DATASET_ID}/files?version={VERSION}"
DATACITE_API = f"https://api.datacite.org/dois/{DOI}"
USER_AGENT = "Poyang-basin-research-data-audit/1.0.1"
ALLOWED_DOWNLOAD_HOSTS = {"data.mendeley.com", "api.mendeley.com"}

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_DIR / "01_数据" / "公开原始数据"
SNAPSHOT_DATE = datetime.now().astimezone().date().isoformat()


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        return response.read()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_snapshot_once(path: Path, payload: object) -> None:
    if path.exists():
        return
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_filename(value: object) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise RuntimeError(f"接口返回了不安全的文件名：{value!r}")
    if Path(value).suffix.lower() != ".xlsx":
        raise RuntimeError(f"核心文件不是预期的xlsx文件：{value!r}")
    return value


def validate_download_url(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"接口缺少下载地址：{value!r}")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise RuntimeError(f"拒绝非白名单HTTPS下载地址：{value!r}")
    return value


def download_verified(item: dict) -> tuple[str, str, int, str]:
    filename = validate_filename(item.get("filename"))
    details = item["content_details"]
    expected_hash = details["sha256_hash"].lower()
    expected_size = int(details["size"])
    target = RAW_DIR / filename

    if target.exists():
        local_hash = sha256_file(target)
        if target.stat().st_size != expected_size or local_hash != expected_hash:
            raise RuntimeError(f"已有原始文件与服务器记录不一致，拒绝覆盖：{target}")
        return filename, local_hash, target.stat().st_size, "已存在，校验通过"

    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()

    download_url = validate_download_url(details.get("download_url"))
    request = Request(download_url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(request, timeout=300) as response, part.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        local_hash = digest.hexdigest()
        if size != expected_size or local_hash != expected_hash:
            raise RuntimeError(
                f"下载校验失败：{filename}；大小 {size}/{expected_size}；"
                f"SHA-256 {local_hash}/{expected_hash}"
            )
        os.replace(part, target)
        return filename, local_hash, size, "本次下载，校验通过"
    except Exception:
        if part.exists():
            part.unlink()
        raise


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    file_items = json.loads(fetch_bytes(FILES_API))
    datacite = json.loads(fetch_bytes(DATACITE_API))
    save_snapshot_once(
        RAW_DIR / f"00_Mendeley_v1_文件接口快照_{SNAPSHOT_DATE}.json",
        file_items,
    )
    save_snapshot_once(
        RAW_DIR / f"00_DataCite_DOI元数据快照_{SNAPSHOT_DATE}.json",
        datacite,
    )

    selected = sorted(
        (
            item
            for item in file_items
            if isinstance(item.get("filename"), str)
            and item["filename"].endswith(("_Qobs.xlsx", "_rainfall.xlsx"))
        ),
        key=lambda item: item["filename"],
    )
    if len(selected) != 14:
        raise RuntimeError(f"预期 14 个核心文件，接口实际筛得 {len(selected)} 个")

    downloaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for item in selected:
        filename, local_hash, local_size, status = download_verified(item)
        details = item["content_details"]
        rows.append(
            {
                "filename": filename,
                "mendeley_file_id": item["id"],
                "doi": DOI,
                "version": VERSION,
                "license": LICENSE,
                "server_sha256": details["sha256_hash"],
                "local_sha256": local_hash,
                "server_size_bytes": details["size"],
                "local_size_bytes": local_size,
                "server_created_date": details["created_date"],
                "downloaded_at": downloaded_at,
                "source_url": validate_download_url(details.get("download_url")),
                "status": status,
            }
        )
        print(f"{status}：{filename}")

    manifest = RAW_DIR / "00_核心文件来源与校验清单.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"完成：14 个核心文件全部通过 SHA-256 与大小校验。")
    print(f"清单：{manifest}")


if __name__ == "__main__":
    main()
