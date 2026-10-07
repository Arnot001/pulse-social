"""Focused checks for the approved Windows release icon; no application startup."""
import hashlib
import os
import re
import struct
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'platforms' / 'tiktok' / 'favicon.ico'
APPROVED_SHA256 = '245424d7bf26ac7b368967b5cc2adc8190aa1b1f2994deab4e66ccfd34c0a9cb'
SIZES = {16, 32, 48, 64, 128, 256}


def test_approved_artwork_is_unchanged():
    assert hashlib.sha256(ICON.read_bytes()).hexdigest() == APPROVED_SHA256


def test_icon_has_all_required_decodable_windows_sizes():
    with Image.open(ICON) as image:
        assert image.format == 'ICO'
        assert {(size, size) for size in SIZES} <= image.ico.sizes()
        for size in SIZES:
            frame = image.ico.getimage((size, size)).convert('RGBA')
            assert frame.size == (size, size) and frame.getbbox()


def test_pyinstaller_and_setup_use_the_same_existing_asset():
    build = (ROOT / 'release/build_beta.ps1').read_text(encoding='utf-8')
    match = re.search(r'\$IconPath = Join-Path \$RepoRoot "([^"]+)"', build)
    assert match and ROOT.joinpath(*match[1].split('\\')) == ICON
    assert '"--icon", $IconPath' in build
    setup = (ROOT / 'release/PulseSocial.iss').read_text(encoding='utf-8')
    match = re.search(r'^SetupIconFile=(.+)$', setup, re.MULTILINE)
    assert match and (ROOT / 'release').joinpath(*match[1].split('\\')).resolve() == ICON
    assert 'UninstallDisplayIcon={app}\\pulse_social.ico' in setup
    assert 'Source: "..\\platforms\\tiktok\\favicon.ico"; DestDir: "{app}"; DestName: "pulse_social.ico"; Flags: ignoreversion' in setup


@pytest.mark.parametrize('location', ['autoprograms', 'autodesktop'])
def test_shortcuts_explicitly_use_installed_icon_file(location):
    setup = (ROOT / 'release/PulseSocial.iss').read_text(encoding='utf-8')
    entry = next(line for line in setup.splitlines() if line.startswith(f'Name: "{{{location}}}'))
    assert 'Filename: "{app}\\{#MyAppExeName}"' in entry
    assert 'IconFilename: "{app}\\pulse_social.ico"' in entry
    assert 'IconIndex:' not in entry


def assert_embedded_icon_matches(executable):
    """Compare every source ICO image payload with the real PE icon resources."""
    import pefile

    source = ICON.read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', source)
    assert (reserved, kind) == (0, 1)
    expected = {}
    for index in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', source, 6 + index * 16)
        expected[(width or 256, height or 256)] = source[offset:offset + length]
    with pefile.PE(str(executable)) as pe:
        icons = next(entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 3)
        payloads = {pe.get_data(lang.data.struct.OffsetToData, lang.data.struct.Size)
                    for entry in icons.directory.entries for lang in entry.directory.entries}
        assert all(payload in payloads for payload in expected.values()), str(executable)
        groups = next(entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 14)
        group = groups.directory.entries[0].directory.entries[0].data.struct
        data = pe.get_data(group.OffsetToData, group.Size)
        _, kind, count = struct.unpack_from('<HHH', data)
        dimensions = {(data[6 + index * 14] or 256, data[7 + index * 14] or 256) for index in range(count)}
        assert kind == 1 and set(expected) <= dimensions


@pytest.mark.parametrize('variable', ['PULSE_ICON_CHECK_APP', 'PULSE_ICON_CHECK_SETUP'])
def test_built_executable_contains_approved_icon(variable):
    path = os.environ.get(variable)
    if not path:
        pytest.skip('Set artifact paths after the beta build to validate embedded PE icons')
    assert_embedded_icon_matches(Path(path))
