"""Save and validate Amazon listing galleries returned by SellerSprite keepa_info."""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from PIL import Image


ASIN = re.compile(r"[A-Z0-9]{10}")
IMAGE_PATH = re.compile(r"/images/I/([A-Za-z0-9+_%=-]+)(?:\._[A-Za-z0-9_,]+_)?\.jpg", re.I)
AMAZON_IMAGE_HOSTS = {"images-na.ssl-images-amazon.com", "m.media-amazon.com"}
MARKETS = set("US JP UK DE FR IT ES CA IN MX BR AU AE".split())
FIELDS = (
    "marketplace", "asin", "group", "pos", "slot", "file", "captured_at", "note",
    "status", "source_url", "download_url", "width", "height", "sha256",
)


def image_id(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    match = IMAGE_PATH.fullmatch(parsed.path)
    if parsed.scheme == "https" and parsed.netloc in AMAZON_IMAGE_HOSTS and match:
        return match[1]
    return None


def write_bytes(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(data)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def fetch_image(row, output):
    key = image_id(row["source_url"])
    if not key:
        return dict(row, status="invalid_url")
    candidates = (
        f"https://m.media-amazon.com/images/I/{key}._AC_US600_.jpg",
        row["source_url"],
    )
    for url in dict.fromkeys(candidates):
        result = subprocess.run(
            ["curl", "-fsS", "--max-time", "12", "--max-filesize", "12000000", url],
            capture_output=True,
        )
        if result.returncode:
            continue
        try:
            with Image.open(io.BytesIO(result.stdout)) as img:
                img.load()
                if img.format != "JPEG":
                    continue
                width, height = img.size
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
        # Use a content-addressed path so a rerun cannot change old evidence files.
        digest = hashlib.sha256(result.stdout).hexdigest()
        path = Path(row["asin"]) / f'{row["pos"]:02d}-{digest[:16]}.jpg'
        (output / path).parent.mkdir(exist_ok=True)
        write_bytes(output / path, result.stdout)
        return dict(row, status="ok", download_url=url, file=path.as_posix(),
                    width=width, height=height, sha256=digest)
    return dict(row, status="download_failed")


def gallery_rows(request):
    marketplace = request["marketplace"]
    if marketplace not in MARKETS:
        raise ValueError(f"Unsupported marketplace: {marketplace}")
    seen = set()
    for group, asins in request["groups"].items():
        for raw_asin in asins:
            asin = raw_asin.strip().upper()
            if not ASIN.fullmatch(asin):
                raise ValueError(f"Invalid ASIN: {raw_asin}")
            if asin in seen:
                continue
            seen.add(asin)
            row = dict(marketplace=marketplace, group=group, asin=asin,
                       captured_at=request["captured_at"])
            data = request["results"].get(asin)
            if not data:
                yield dict(row, status="query_failed")
                continue
            if (data.get("asin") != asin or data.get("dataAsin") not in (None, asin)
                    or data.get("marketplace") not in (None, marketplace)):
                yield dict(row, status="identity_mismatch")
                continue
            urls = data.get("imageUrls")
            if not isinstance(urls, list) or not urls:
                yield dict(row, status="gallery_missing")
                continue
            main_id = image_id(data.get("imageUrl"))
            first_id = image_id(urls[0])
            conflicting_main = bool(main_id and main_id != first_id
                                    and any(image_id(url) == main_id for url in urls[1:]))
            for pos, url in enumerate(urls, 1):
                slot = "副图"
                if pos == 1:
                    slot = "主图" if main_id and first_id == main_id else "首图待核"
                elif conflicting_main:
                    slot = "图位待核"
                yield dict(row, pos=pos, slot=slot, source_url=url, status="pending")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.source.read_text(encoding="utf-8-sig"))
    rows = list(gallery_rows(request))
    if not rows:
        parser.error("No competitor ASINs were supplied")
    args.out.mkdir(parents=True, exist_ok=True)

    def download(row):
        return fetch_image(row, args.out) if row["status"] == "pending" else row

    with ThreadPoolExecutor(max_workers=4) as executor:
        manifest = list(executor.map(download, rows))
    manifest_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(manifest_buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(manifest)
    write_bytes(args.out / "manifest.csv", manifest_buffer.getvalue().encode("utf-8-sig"))
    saved = Counter(row["asin"] for row in manifest if row["status"] == "ok")
    listed = Counter(row["asin"] for row in manifest if "pos" in row)
    print(json.dumps({asin: [saved[asin], listed[asin]]
                      for asin in dict.fromkeys(row["asin"] for row in manifest)}))
    return int(any(row["status"] != "ok" for row in manifest))


if __name__ == "__main__":
    raise SystemExit(main())
