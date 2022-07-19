import logging
import re
import sys

from ..config import config
from ..utils import getpass_handle, input_handle
from ..main import login, logout
from ..errors import HTTPException, LoginFailed, UnhandledHTTPError
from ..network import Net

# I know this sound stupid
# But i only know this to check if it's email or username
email_regex = r'.{1,}@.{1,}\..{1,}'

log = logging.getLogger(__name__)

def logout_with_err_handler(args):
    if not args.login:
        return
    # Make sure that we are really LOGGED IN
    # To prevent error while logging out
    try:
        logged_in = Net.mangadex.check_login()
    except Exception:
        logged_in = False

    if not logged_in:
        return

    logout_success = False
    for _ in range(5):
        attempt = _ + 1
        try:
            logout()
        except HTTPException as e:
            log.info(
                'Logout failed because of MangaDex server error, status code: %s. ' \
                'Trying again... (attempt: %s)',
                e.response.status_code,
                attempt
            )
        else:
            logout_success = True
            break

    if not logout_success:
        log.error("5 attempts logout failed, ignoring...")

def login_with_err_handler(args):
    if not args.login and config.login_cache:
        Net.mangadex.login_from_cache()

        if Net.mangadex.check_login():
            return

    if args.login:
        email = None
        username = None

        username = args.login_username or input_handle("MangaDex username / email => ")
        password = args.login_password or getpass_handle("MangaDex password => ")
        # Ability to login with email
        is_email = re.match(email_regex, username)
        if is_email is not None:
            email = is_email.group()
            username = None

        # Logging in
        login_success = False
        for _ in range(5):
            attempt = _ + 1
            try:
                login(password, username, email)
            except LoginFailed as e:
                sys.exit(1)
            except ValueError as e:
                log.error(e)
                sys.exit(1)
            except HTTPException as e:
                log.info(
                    'Login failed because of MangaDex server error, status code: %s. ' \
                    'Trying again... (attempt: %s)',
                    e.response.status_code,
                    attempt
                )
            else:
                login_success = True
                break

        if not login_success:
            log.error("5 attempts login failed, exiting...")
            sys.exit(1)