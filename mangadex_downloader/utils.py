import os
import re
import time
import signal
import json
import logging
import sys
from io import BytesIO
from pathvalidate import sanitize_filename
from enum import Enum
from getpass import getpass
from .errors import InvalidURL, NotLoggedIn
from .downloader import FileDownloader, _cleanup_jobs

log = logging.getLogger(__name__)

# Compliance with Tachiyomi local JSON format
class MangaStatus(Enum):
    Ongoing = "1"
    Completed = "2"
    Hiatus = "6"
    Cancelled = "5"

def validate_url(url):
    """Validate mangadex url and return the uuid"""
    re_url = re.compile(r'([a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12})')
    match = re_url.search(url)
    if match is None:
        raise InvalidURL('\"%s\" is not valid MangaDex URL' % url)
    return match[1]

def validate_legacy_url(url):
    """Validate old mangadex url and return the id"""
    re_url = re.compile(r'mangadex\.org\/(title|manga|chapter)\/(?P<id>[0-9]{1,})')
    match = re_url.search(url)
    if match is None:
        raise InvalidURL('\"%s\" is not valid MangaDex URL' % url)
    return match['id']

def validate_group_url(url):
    """Validate group mangadex url and return the id"""
    if url is None:
        return
    all_group = url.lower().strip() == "all"
    return "all" if all_group else validate_url(url)

def download(url, file, progress_bar=True, replace=False, use_requests=False, **headers):
    """Shortcut for :class:`FileDownloader`"""
    downloader = FileDownloader(
        url,
        file,
        progress_bar,
        replace,
        use_requests,
        **headers
    )
    downloader.download()
    downloader.cleanup()

def write_details(manga, path):
    # Parse authors
    authors = "".join(
        f"{author}," if index < (len(manga.authors) - 1) else author
        for index, author in enumerate(manga.authors)
    )

    # Parse artists
    artists = "".join(
        f"{artist}," if index < (len(manga.artists) - 1) else artist
        for index, artist in enumerate(manga.artists)
    )

    data = {
        'title': manga.title,
        'author': authors,
        'artist': artists,
        'description': manga.description,
        'genre': manga.genres,
        'status': MangaStatus[manga.status].value,
        '_status values': [
            "0 = Unknown",
            "1 = Ongoing",
            "2 = Completed",
            "3 = Licensed",
            "4 = Publishing finished",
            "5 = Cancelled",
            "6 = On hiatus",
        ],
    }

    with open(path, 'w') as writer:
        writer.write(json.dumps(data))

def create_chapter_folder(base_path, chapter_title):
    chapter_path = base_path / sanitize_filename(chapter_title)
    if not chapter_path.exists():
        chapter_path.mkdir(exist_ok=True)

    return chapter_path

# This is shortcut to extract data from localization dict structure
# in MangaDex JSON data
# For example: 
# {
#     'attributes': {
#         'en': '...' # This is what we need 
#     }
# }
def get_local_attr(data):
    if not data:
        return ""
    for key, val in data.items():
        return val

class File:
    """A utility for file naming

    Parameter ``file`` can take IO (must has ``name`` object) or str
    """
    def __init__(self, file):
        full_name = file.name if hasattr(file, 'name') else file
        name, ext = os.path.splitext(full_name)

        self.name = name
        self.ext = ext

    def __repr__(self) -> str:
        return self.full_name

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        """Return file name with extension file"""
        return self.name + self.ext

    def change_name(self, new_name):
        """Change file name to new name, but the extension file will remain same"""
        self.name = new_name

def input_handle(*args, **kwargs):
    """Same as input(), except when user hit EOFError the function automatically called sys.exit(0)"""
    try:
        return input(*args, **kwargs)
    except EOFError:
        sys.exit(0)

def getpass_handle(*args, **kwargs):
    """Same as getpass(), except when user hit EOFError the function automatically called sys.exit(0)"""
    try:
        return getpass(*args, **kwargs)
    except EOFError:
        sys.exit(0)

def comma_separated_text(array):
    # Opening square bracket
    text = "["

    # Append first item
    text += array.pop(0)

    # Add the rest of items
    for item in array:
        text += f', {item}'

    # Closing square bracket
    text += ']'

    return text