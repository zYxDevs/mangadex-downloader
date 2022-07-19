import logging
import re

from ..fetcher import get_chapter, get_list, get_manga
from ..errors import ChapterNotFound, InvalidManga, InvalidMangaDexList, InvalidURL, MangaDexException
from ..utils import validate_url
from ..main import (
    download as dl_manga,
    download_chapter as dl_chapter,
    download_list as dl_list,
    download_legacy_chapter as dl_legacy_chapter,
    download_legacy_manga as dl_legacy_manga
)

log = logging.getLogger(__name__)

# Helper for building smart select url regex
def _build_re(_type):
    # Legacy support
    if 'legacy-manga' in _type:
        return r'mangadex\.org\/(title|manga)\/(?P<id>[0-9]{1,})'
    elif 'legacy-chapter' in _type:
        return r'mangadex\.org\/chapter\/(?P<id>[0-9]{1,})'
    elif _type == 'manga':
        return r'mangadex\.org\/(title|manga)\/(?P<id>[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12})'

    else:
        return (
            r"mangadex\.org\/%s\/(?P<id>[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12})"
            % _type
        )

def download_manga(url, args, legacy=False):
    if args.group and args.no_group_name:
        raise MangaDexException("--group cannot be used together with --no-group-name")

    if (
        args.start_chapter is not None
        and args.end_chapter is not None
        and args.start_chapter > args.end_chapter
    ):
        raise MangaDexException("--start-chapter cannot be more than --end-chapter")

    if (
        args.start_page is not None
        and args.end_page is not None
        and args.start_page > args.end_page
    ):
        raise MangaDexException("--start-page cannot be more than --end-page")

    # We cannot allow if --range and other range options (such as: --start-chapter) together
    range_forbidden_args = {
        'start_chapter': '--start-chapter',
        'end_chapter': '--end-chapter',
        'start_page': '--start-page',
        'end_page': '--end-page',
        'no_oneshot_chapter': '--no-oneshot-chapter'
    }
    for name, arg in range_forbidden_args.items():
        value = getattr(args, name)
        if args.range and value:
            raise MangaDexException(f'--range cannot be used together with {arg}')

    args = (
        url,
        args.folder,
        args.replace,
        args.use_compressed_image,
        args.start_chapter,
        args.end_chapter,
        args.start_page,
        args.end_page,
        args.no_oneshot_chapter,
        args.language,
        args.cover,
        args.save_as,
        args.use_alt_details,
        args.no_group_name,
        args.group,
        args.enable_legacy_sorting,
        args.use_chapter_title,
        args.unsafe,
        args.no_verify,
        args.range
    )

    if legacy:
        dl_legacy_manga(*args)
    else:
        dl_manga(*args)
        

def download_chapter(url, args, legacy=False):

    if args.range:
        raise MangaDexException('--range option is not available for chapter download')

    args = (
        url,
        args.folder,
        args.replace,
        args.start_page,
        args.end_page,
        args.use_compressed_image,
        args.save_as,
        args.no_group_name,
        args.enable_legacy_sorting,
        args.use_chapter_title,
        args.unsafe,
        args.no_verify
    )

    if legacy:
        dl_legacy_chapter(*args)
    else:
        dl_chapter(*args)

def _error_list(option):
    raise MangaDexException(f"{option} is not allowed when download a list")

def download_list(url, args):
    if args.start_chapter:
        _error_list('--start-chapter')
    elif args.end_chapter:
        _error_list('--end-chapter')
    elif args.start_page:
        _error_list('--start-page')
    elif args.end_page:
        _error_list('--end-page')
    elif args.range:
        _error_list('--range')

    if args.group and args.no_group_name:
        raise MangaDexException("--group cannot be used together with --no-group-name")

    dl_list(
        url,
        args.folder,
        args.replace,
        args.use_compressed_image,
        args.language,
        args.cover,
        args.save_as,
        args.no_group_name,
        args.group,
        args.enable_legacy_sorting,
        args.use_chapter_title,
        args.unsafe,
        args.no_verify
    )

# Legacy support
download_legacy_manga = lambda url, args: download_manga(url, args, True)
download_legacy_chapter = lambda url, args: download_chapter(url, args, True)

valid_types = [
    "manga",
    "list",
    "chapter",
    "legacy-manga",
    "legacy-chapter"
]

funcs = {i: globals()[f"download_{i.replace('-', '_')}"] for i in valid_types}

regexs = {i: _build_re(i) for i in valid_types}

class URL:
    def __init__(self, func, _id):
        self.func = func
        self.id = _id
    
    def __call__(self, args, _type=None):
        if _type is not None:
            self.func = funcs[_type]
        self.func(self.id, args)

    def __repr__(self) -> str:
        return '<URL func = "%s" id = "%s">' % (
            self.func.__name__,
            self.id
        )

def build_URL_from_type(_type, _id):
    return URL(funcs[_type], _id)

def smart_select_url(url):
    """Wisely determine type url. The process is checking given url one by one"""
    log.info(f"Checking url = {url}")
    found = False
    func = None
    _id = None
    for _type, regex in regexs.items():
        # Match pattern regex
        match = re.search(regex, url)
        if match is None:
            continue

        # Get UUID
        _id = match['id']

        # Get download function
        func = funcs[_type]

        if 'legacy-' in _type:
            # Only for legacy url
            # Because inside `download_legacy_*` has already validator legacy url.
            # Unlike download function for new id, if it's parsed id, it will throw error.
            _id = url

        found = True

        if found:
            break

    # If none of patterns is match, grab UUID instantly and then
    # fetch one by one, starting from manga, list, and then chapter.
    if not found:
        _id = validate_url(url)

        # Manga
        try:
            get_manga(_id)
        except InvalidManga:
            pass
        else:
            func = funcs['manga']

        # MDlist
        try:
            get_list(_id)
        except InvalidMangaDexList:
            pass
        else:
            func = funcs['list']

        # Chapter
        try:
            get_chapter(_id)
        except ChapterNotFound:
            pass
        else:
            func = funcs['chapter']

        # None of them is found in MangaDex
        # raise error
        if func is None:
            raise InvalidURL(f"'{url}' is not valid MangaDex URL")

    return URL(func, _id)