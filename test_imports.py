print("Importing main module")
from mangadex_downloader import __version__, download

print("Importing cli module")
from mangadex_downloader.__main__ import main

print(f"Test imports mangadex-downloader v{__version__} is success")