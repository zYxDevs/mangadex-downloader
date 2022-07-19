import logging
from functools import lru_cache
from requests.exceptions import HTTPError
from .errors import ChapterNotFound, GroupNotFound, HTTPException, InvalidManga, InvalidMangaDexList, MangaDexException, UserNotFound
from .network import Net, base_url, origin_url
from .utils import validate_url

log = logging.getLogger(__name__)

def get_manga(manga_id):
    url = '{0}/manga/{1}'.format(base_url, manga_id)
    params = {
        'includes[]': ['author', 'artist', 'cover_art']
    }
    r = Net.mangadex.get(url, params=params)
    if r.status_code == 404:
        raise InvalidManga('Manga \"%s\" cannot be found' % manga_id)
    return r.json()

def get_legacy_id(_type, _id):
    # Mark it as deprecated
    # bye bye :(
    log.warning(
        'Old MangaDex URL are deprecated and will be removed any time soon. ' \
        'Please use the new MangaDex URL'
    )

    supported_types = ['manga', 'chapter', 'title']

    # Alias for title
    if _type == 'manga':
        _type = 'title'

    if _type not in supported_types:
        raise MangaDexException("\"%s\" is not supported type" % _type)

    # Normally, this can be done from API url. But, somehow the API endpoint (/legacy/mapping)
    # throwing server error (500) in response. We will use this, until the API gets fixed.
    # NOTE: The error only applied to "chapter" type, "manga" type is working fine.
    url = '{0}/{1}/{2}'.format(origin_url, _type, _id)

    # The process is by sending request to "mangadex.org" (not "api.mangadex.org"), if it gets redirected,
    # the legacy id is exist. Otherwise the legacy id is not found in MangaDex database
    r = Net.mangadex.get(url, allow_redirects=False)

    if r.status_code >= 300:
        # Redirected request, the legacy id is exist
        location_url = r.headers.get('location')

        # Get the new id
        url = validate_url(location_url)
    elif _type == 'title':
        raise InvalidManga('Manga \"%s\" cannot be found' % _id)
    elif _type == 'chapter':
        raise ChapterNotFound(f"Chapter {_id} cannot be found")

    return url

@lru_cache(maxsize=1048)
def get_author(author_id):
    url = '{0}/author/{1}'.format(base_url, author_id)
    r = Net.mangadex.get(url)
    return r.json()

@lru_cache(maxsize=1048)
def get_user(user_id):
    url = '{0}/user/{1}'.format(base_url, user_id)
    r = Net.mangadex.get(url)
    if r.status_code == 404:
        raise UserNotFound(f"user {user_id} cannot be found")
    return r.json()

@lru_cache(maxsize=1048)
def get_cover_art(cover_id):
    url = '{0}/cover/{1}'.format(base_url, cover_id)
    r = Net.mangadex.get(url)
    return r.json()

def get_chapter(chapter_id):
    url = '{0}/chapter/{1}'.format(base_url, chapter_id)
    params = {
        'includes[]': ['scanlation_group', 'user']
    }
    r = Net.mangadex.get(url, params=params)
    if r.status_code == 404:
        raise ChapterNotFound(f"Chapter {chapter_id} cannot be found")
    return r.json()

def get_list(list_id):
    url = '{0}/list/{1}'.format(base_url, list_id)
    r = Net.mangadex.get(url)
    if r.status_code == 404:
        raise InvalidMangaDexList(f"List {list_id} cannot be found")
    return r.json()

@lru_cache(maxsize=1048)
def get_group(group_id):
    url = '{0}/group/{1}'.format(base_url, group_id)
    r = Net.mangadex.get(url)
    if r.status_code == 404:
        raise GroupNotFound(f"Scanlator group {group_id} cannot be found")
    return r.json()

def get_all_chapters(manga_id, lang):
    url = '{0}/manga/{1}/aggregate'.format(base_url, manga_id)
    r = Net.mangadex.get(url, params={'translatedLanguage[]': [lang]})
    return r.json()

def get_chapter_images(chapter_id):
    url = '{0}/at-home/server/{1}'.format(base_url, chapter_id)
    r = Net.mangadex.get(url)
    return r.json()

def get_bulk_chapters(manga_id):
    url = f'{base_url}/manga/{manga_id}/feed'
    includes = ['scanlation_group', 'user']
    # Validation content rating is on main.py
    content_ratings = [
        'safe',
        'suggestive',
        'erotica',
        'pornographic'
    ]
    params = {
        'limit': 500,
        'includes[]': includes,
        'contentRating[]': content_ratings
    }
    r = Net.mangadex.get(url, params=params)
    return r.json()