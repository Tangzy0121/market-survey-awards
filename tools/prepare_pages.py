"""Build the public reading site from the verified original release bundle."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
from urllib.parse import unquote, urlparse
from zipfile import ZipFile


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ('href', 'src') and value:
                self.references.append(value)


def prepare(archive_path, expected_digest, destination):
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if digest != expected_digest:
        raise ValueError('Release bundle SHA-256 does not match the pinned digest')

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if not path.parts or path.parts[0] != 'market-survey-awards':
                raise ValueError(f'Unexpected archive root: {entry.filename}')
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:
                raise ValueError(f'Unsafe archive path: {entry.filename}')
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f'Unexpected symbolic link: {entry.filename}')
            target = destination.joinpath(*path.parts[1:])
            if not target.resolve().is_relative_to(destination):
                raise ValueError(f'Archive path escapes the site: {entry.filename}')
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)

    for name in ('index.html', 'sources.json', 'file-manifest.json', 'preview.png', 'README.txt'):
        shutil.copy2(root / 'output' / name, destination / name)
    (destination / '.nojekyll').write_text('', encoding='utf-8')

    manifest = json.loads((destination / 'file-manifest.json').read_text(encoding='utf-8'))
    for record in manifest:
        path = destination / record['file']
        if path.stat().st_size != record['bytes']:
            raise ValueError(f'Original file has the wrong size: {record["file"]}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError(f'Original file checksum failed: {record["file"]}')

    html = (destination / 'index.html').read_text(encoding='utf-8')
    parser = AssetReferences()
    parser.feed(html)
    for reference in parser.references:
        parsed = urlparse(reference)
        if not parsed.scheme and parsed.path:
            path = destination / unquote(parsed.path)
            if not path.is_file():
                raise ValueError(f'Reading page asset is missing: {reference}')

    page_count = len(list((destination / 'files/report-pages').glob('*.jpg')))
    appendix_count = len(list((destination / 'files').glob('2024-appendix-*.docx')))
    segment_count = html.count('class="episode"')
    if (page_count, appendix_count, segment_count) != (68, 10, 67):
        raise ValueError('The site does not contain the full reading collection')
    print(f'Site verified: {page_count} report pages, {appendix_count} appendices, {segment_count} video links')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', type=Path, default=Path('_site'))
    args = parser.parse_args()
    prepare(args.archive, args.sha256, args.destination)
