from .fetcher import get_cover_art
from .utils import File
from .language import get_language

valid_cover_types = [
    'original',
    '512px',
    '256px',
    'none'
]

default_cover_type = "original"

class CoverArt:
    def __init__(self, cover_id=None, data=None):
        self.data = data or get_cover_art(cover_id)['data']
        self.id = self.data['id']
        attr = self.data['attributes']

        # Description
        self.description = attr['description']

        # Volume
        self.volume = attr['volume']

        # File cover
        self.file = File(attr['fileName'])

        # Locale
        self.locale = get_language(attr['locale'])