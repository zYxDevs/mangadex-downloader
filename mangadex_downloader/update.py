import os
import io
import sys
import subprocess
import sys
import logging
import tempfile
import zipfile
from packaging.version import parse as parse_version
from importlib.util import find_spec
from pathlib import Path

from .network import Net
from .utils import download
from . import __version__

current_version = parse_version(__version__)

log = logging.getLogger(__name__)

# A trick for checking if this in independent executable or not
executable = hasattr(sys, 'frozen')

is_64bits = sys.maxsize > 2**32

architecture = 'x64' if is_64bits else 'x86'

# Helper functions
def _get_api_tags():
    r = Net.requests.get('https://api.github.com/repos/mansuf/mangadex-downloader/git/refs/tags')
    return [
        version_info['ref'].replace('refs/tags/', '')
        for version_info in r.json()
    ]

def _get_asset(_version):
    version = str(_version)
    if not version.startswith('v'):
        version = f'v{version}'

    r = Net.requests.get('https://api.github.com/repos/mansuf/mangadex-downloader/releases')
    for release_info in r.json():
        if version == release_info['tag_name']:
            assets = release_info['assets']
            filename = 'mangadex-dl_{arch}_{version}.zip'.format(arch=architecture, version=version)
            for asset in assets:
                if asset['name'] == filename:
                    return asset['browser_download_url']

def check_version():
    # Get latest version
    try:
        versions = _get_api_tags()
        latest_version = parse_version(max(versions, key=parse_version))
    except Exception as e:
        log.error(f"Failed to check update, reason: {e}")
        return False

    return latest_version if latest_version > current_version else None

def update_app():
    latest_version = check_version()

    if latest_version == False:
        sys.exit(1)

    if latest_version:

        log.info(f"Found latest version mangadex-downloader (v{latest_version})")

        # Get url update
        try:
            url_update = _get_asset(latest_version)
        except Exception as e:
            log.error(f"Failed to get update url, reason: {e}")
            sys.exit(1)

        current_path = Path(sys.executable).parent

        if executable:
            try:
                temp_folder = Path(tempfile.mkdtemp(suffix='md_downloader_update'))
            except Exception as e:
                log.error(f"Failed to create temporary folder, reason: {e}")
                sys.exit(1)

            update_file_path = str(temp_folder / f'{latest_version}.zip')

            log.info(f"Downloading update v{latest_version}")
            # Download update
            try:
                download(url_update, update_file_path, use_requests=True)
            except Exception as e:
                log.error(f"Failed to download update, reason: {e}")
                sys.exit(1)

            # Extract update
            try:
                with zipfile.ZipFile(update_file_path, 'r') as update:
                    update.extractall(Path(update_file_path).parent)
            except Exception as e:
                log.error(f"Failed to extract update, reason: {e}")
                sys.exit(1)

            extracted_update_path = str(temp_folder / 'mangadex-dl')

            with open((temp_folder / "install.bat"), "w") as install_script:
                install_script.write("@echo off\n")
                install_script.write("title mangadex-downloader updater\n")
                install_script.write("timeout 1 >nul 2>&1 \n")
                install_script.write("echo Updating mangadex-downloader from v%s to v%s\n" % (
                    current_version,
                    latest_version
                ))
                install_script.write("xcopy /S /E /Y \"%s\" \"%s\" >nul 2>&1 \n" % (extracted_update_path, current_path))
                install_script.write("start cmd /c \"rmdir /Q /S \"%s\"\"\n" % temp_folder)
                install_script.write("echo Successfully updated mangadex-downloader to v%s\n" % latest_version)
                install_script.write("echo You may close this window\n")
                install_script.write("pause >nul 2>&1 \n")
                install_script.write("exit\n")
            os.system("start cmd /c \"\"%s\"\"" % (temp_folder / "install.bat"))
            sys.exit(0)
        else:
            subprocess.run([
                sys.executable,
                '-m',
                'pip',
                'install',
                '-U',
                'mangadex-downloader',
            ])
    else:
        log.info('This version mangadex-downloader is up-to-date')


