import logging
import queue

from .errors import MangaDexException, NotLoggedIn
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
            'erotica',
        ]

        if self.unsafe:
            content_ratings.append('pornographic')

        params = {
            'includes[]': includes,
            'title': self.title,
            'limit': self.limit,
            'offset': self.offset,
            'contentRating[]': content_ratings
        }
        url = f'{base_url}/manga'
        r = Net.requests.get(url, params=params)
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

        lib = {}
        for stat in self.statuses:
            lib[stat] = []
        self.library = lib

        logged_in = Net.requests.check_login()
        if not logged_in:
            raise NotLoggedIn("Retrieving user library require login")

        self._parse_reading_status()

    def _parse_reading_status(self):
        r = Net.requests.get(f'{base_url}/manga/status')
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

            if not self.unsafe and manga.content_rating == ContentRating.Pornographic:
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
        r = Net.requests.get(url, params=params)
        data = r.json()

        items = data['data']

        for item in items:
            self.queue.put(Manga(data=item))
        
        self.offset += len(items)

class IteratorMangaFromList(BaseIterator):
    def __init__(self, _id=None, unsafe=False):
        super().__init__()

        self.id = _id
        self.limit = 100
        self.unsafe = unsafe
        self.name = None # type: str
        self.user = None # type: User

        self.manga_ids = []

        self._parse_list()

    def _parse_list(self):
        data = get_list(self.id)['data']

        self.name = data['attributes']['name']
        
        for rel in data['relationships']:
            _type = rel['type']
            _id = rel['id']
            if _type == 'manga':
                self.manga_ids.append(_id)
            elif _type == 'user':
                self.user = User(_id)
    
    def next(self) -> Manga:
        return self.queue.get_nowait()
    
    def fill_data(self):
        ids = self.manga_ids
        includes = ['author', 'artist', 'cover_art']
        content_ratings = [
            'safe',
            'suggestive',
            'erotica',
        ]

        if self.unsafe:
            content_ratings.append('pornographic')

        limit = self.limit
        if ids:
            param_ids = ids[:limit]
            del ids[:len(param_ids)]
            params = {
                'includes[]': includes,
                'limit': limit,
                'contentRating[]': content_ratings,
                'ids[]': param_ids
            }
            url = f'{base_url}/manga'
            r = Net.requests.get(url, params=params)
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