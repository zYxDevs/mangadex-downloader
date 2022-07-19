import logging
import queue

from .mdlist import MangaDexList
from .errors import HTTPException, MangaDexException, NotLoggedIn
from .network import Net, base_url
from .manga import ContentRating, Manga
from .fetcher import get_list
from .user import User

log = logging.getLogger(__name__)

class BaseIterator:
    def __init__(self):
        self.queue = queue.Queue()
        self.offset = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.queue.empty():
            # Maximum number of results from MangaDex API
            if self.offset >= 10000:
                raise StopIteration()
            else:
                self.fill_data()

        try:
            return self.next()
        except queue.Empty:
            raise StopIteration()

    def fill_data(self):
        raise NotImplementedError

    def next(self):
        raise NotImplementedError

class IteratorBulkChapters(BaseIterator):
    """This class is returning 500 chapters in single yield
    and will be used for IteratorChapter internally

    Each of returned chapters from this class
    are raw data (dict type) and should not be used directly.
    """
    def __init__(self, manga_id, lang):
        super().__init__()

        self.limit = 500
        self.id = manga_id
        self.language = lang

    def next(self) -> dict:
        return self.queue.get_nowait()
    
    def fill_data(self):
        url = f'{base_url}/manga/{self.id}/feed'
        includes = ['scanlation_group', 'user']
        content_ratings = [
            'safe',
            'suggestive',
            'erotica',
            'pornographic'
        ]
        params = {
            'limit': self.limit,
            'offset': self.offset,
            'includes[]': includes,
            'contentRating[]': content_ratings,
            'translatedLanguage[]': [self.language],
        }

        r = Net.mangadex.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(item)

        self.offset += len(items)

class IteratorManga(BaseIterator):
    def __init__(self, title, unsafe=False):
        super().__init__()

        self.limit = 100
        self.title = title
        self.unsafe = unsafe

    def next(self) -> Manga:
        return self.queue.get_nowait()

    def fill_data(self):
        includes = ['author', 'artist', 'cover_art']
        content_ratings = [
            'safe',
            'suggestive',
        ]

        if self.unsafe:
            content_ratings.extend(('erotica', 'pornographic'))
        params = {
            'includes[]': includes,
            'title': self.title,
            'limit': self.limit,
            'offset': self.offset,
            'contentRating[]': content_ratings
        }
        url = f'{base_url}/manga'
        r = Net.mangadex.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(Manga(data=item))

        self.offset += len(items)

class IteratorUserLibraryManga(BaseIterator):
    statuses = [
        'reading',
        'on_hold',
        'plan_to_read',
        'dropped',
        're_reading',
        'completed'
    ]

    def __init__(self, status=None, unsafe=False):
        super().__init__()

        self.limit = 100
        self.offset = 0
        self.unsafe = unsafe

        if status is not None and status not in self.statuses:
            raise MangaDexException(f"{status} are not valid status, choices are {set(self.statuses)}")

        self.status = status

        lib = {stat: [] for stat in self.statuses}
        self.library = lib

        if logged_in := Net.mangadex.check_login():
            self._parse_reading_status()
        else:
            raise NotLoggedIn("Retrieving user library require login")

    def _parse_reading_status(self):
        r = Net.mangadex.get(f'{base_url}/manga/status')
        data = r.json()

        for manga_id, status in data['statuses'].items():
            self.library[status].append(manga_id)

    def _check_status(self, manga):
        if self.status is None:
            return True

        manga_ids = self.library[self.status]
        return manga.id in manga_ids

    def next(self) -> Manga:
        while True:
            manga = self.queue.get_nowait()

            if not self.unsafe and manga.content_rating in [
                ContentRating.Pornographic,
                ContentRating.Erotica,
            ]:
                # YOU SHALL NOT PASS
                continue

            if not self._check_status(manga):
                # Filter is used
                continue

            return manga

    def fill_data(self):
        includes = [
            'artist', 'author', 'cover_art'
        ]
        params = {
            'includes[]': includes,
            'limit': self.limit,
            'offset': self.offset,
        }
        url = f'{base_url}/user/follows/manga'
        r = Net.mangadex.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(Manga(data=item))

        self.offset += len(items)

class IteratorMangaFromList(BaseIterator):
    def __init__(self, _id=None, data=None, unsafe=False):
        if _id is None and data is None:
            raise ValueError("atleast provide _id or data")
        elif _id and data:
            raise ValueError("_id and data cannot be together")

        super().__init__()

        self.id = _id
        self.data = data
        self.limit = 100
        self.unsafe = unsafe
        self.name = None # type: str
        self.user = None # type: User

        self.manga_ids = []

        self._parse_list()

    def _parse_list(self):
        data = get_list(self.id)['data'] if self.id else self.data
        self.name = data['attributes']['name']

        for rel in data['relationships']:
            _type = rel['type']
            _id = rel['id']
            if _type == 'manga':
                self.manga_ids.append(_id)
            elif _type == 'user':
                self.user = User(_id)
    
    def next(self) -> Manga:
        while True:
            manga = self.queue.get_nowait()

            if not self.unsafe and manga.content_rating in [
                ContentRating.Pornographic,
                ContentRating.Erotica,
            ]:
                # No unsafe ?
                # No way
                continue

            return manga
    
    def fill_data(self):
        if not (ids := self.manga_ids):
            return
        limit = self.limit
        param_ids = ids[:limit]
        del ids[:len(param_ids)]
        includes = ['author', 'artist', 'cover_art']
        content_ratings = [
            'safe',
            'suggestive',
            'erotica',
            'pornographic' # Filter porn content will be done in next()
        ]

        params = {
            'includes[]': includes,
            'limit': limit,
            'contentRating[]': content_ratings,
            'ids[]': param_ids
        }
        url = f'{base_url}/manga'
        r = Net.mangadex.get(url, params=params)
        data = r.json()

        notexist_ids = param_ids.copy()
        copy_data = data.copy()
        for manga_data in copy_data['data']:
            manga = Manga(data=manga_data)
            if manga.id in notexist_ids:
                notexist_ids.remove(manga.id)

        if notexist_ids:
            for manga_id in notexist_ids:
                log.warning(f'There is ghost (not exist) manga = {manga_id} in list {self.name}')

        for manga_data in data['data']:
            self.queue.put(Manga(data=manga_data))

class IteratorUserLibraryList(BaseIterator):
    def __init__(self):
        super().__init__()

        self.limit = 100
        self.offset = 0

        logged_in = Net.mangadex.check_login()
        if not logged_in:
            raise NotLoggedIn("Retrieving user library require login")

    def next(self) -> MangaDexList:
        return self.queue.get_nowait()

    def fill_data(self):
        params = {
            'limit': self.limit,
            'offset': self.offset,
        }
        url = f'{base_url}/user/list'
        r = Net.mangadex.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(MangaDexList(data=item))

        self.offset += len(items)

class IteratorUserList(BaseIterator):
    def __init__(self, _id=None):
        super().__init__()

        self.limit = 100
        self.user = User(_id)
    
    def next(self) -> MangaDexList:
        return self.queue.get_nowait()

    def fill_data(self):
        params = {
            'limit': self.limit,
            'offset': self.offset,

        }
        url = f'{base_url}/user/{self.user.id}/list'
        try:
            r = Net.mangadex.get(url, params=params)
        except HTTPException:
            # Some users are throwing server error (Bad gateway)
            # MD devs said it was cache and headers issues
            # Reference: https://api.mangadex.org/user/10dbf775-1935-4f89-87a5-a1f4e64d9d94/list
            # For now the app will throw error and tell the user cannot be fetched until it's get fixed

            # HTTPException from session only giving "server throwing ... code" message
            raise HTTPException(
                f"An error occured when getting mdlists from user \"{self.user.id}\". " \
                f"The app cannot fetch all MangaDex lists from user \"{self.user.id}\" " \
                "because of server error. The only solution is to wait until this get fixed " \
                "from MangaDex itself."
            ) from None

        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(MangaDexList(data=item))

        self.offset += len(items)

class IteratorUserLibraryFollowsList(BaseIterator):
    def __init__(self):
        super().__init__()

        self.limit = 100

        logged_in = Net.mangadex.check_login()
        if not logged_in:
            raise NotLoggedIn("Retrieving user library require login")

    def next(self) -> MangaDexList:
        return self.queue.get_nowait()

    def fill_data(self):
        params = {
            'limit': self.limit,
            'offset': self.offset,
        }
        url = f'{base_url}/user/follows/list'
        r = Net.mangadex.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(MangaDexList(data=item))

        self.offset += len(items)