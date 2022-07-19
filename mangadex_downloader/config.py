import binascii
import json
import sys
import threading
import logging
import os
import base64
import traceback
import jwt
from pathlib import Path
from datetime import datetime

from . import format as fmt
from .language import Language, get_language
from .errors import MangaDexException
from .cover import default_cover_type, valid_cover_types

log = logging.getLogger(__name__)

class ConfigTypeError(MangaDexException):
    pass

# Utilities
def _validate_bool(val):
    if not isinstance(val, str):
        return bool(val)
    value = val.strip().lower()

    # Is it 1 or 0 ?
    try:
        return bool(int(value))
    except ValueError:
        pass

    # This is dumb
    if value == "true":
        return True
    elif value == "false":
        return False
    else:
        raise ConfigTypeError(f"'{val}' is not valid boolean value")

def _validate_language(val):
    lang = get_language(val)
    return lang.value

def _validate_cover(val):
    if val not in valid_cover_types:
        raise ConfigTypeError(f"'{val}' is not valid cover type")

    return val

def _validate_format(val):
    fmt.get_format(val)
    return val

_env_dir = os.environ.get('MANGADEXDL_CONFIG_DIR')
home_path = Path(_env_dir) if _env_dir is not None else Path.home()
config_enabled = _validate_bool(os.environ.get('MANGADEXDL_CONFIG_ENABLED'))

# .mangadex-dl dir in home directory
base_path = home_path / '.mangadex-dl'

def init():
    # Create config directory
    try:
        base_path.mkdir(exist_ok=True, parents=True)
    except Exception as e:
        raise MangaDexException(
            f"Failed to create config folder in '{base_path}', " \
            f"reason: {e}. Make sure you have permission to read & write in that directory " \
            "or you can set MANGADEXDL_CONFIG_DIR to another path " \
            "or you can disable config with MANGADEXDL_CONFIG_ENABLED=0"
        ) from None

class _Config:
    path = base_path / 'config.json'
    confs = {
        "login_cache": [
            False, # default value
            _validate_bool, # validator value
        ],
        "language": [
            Language.English.value, # Enum object are not JSON serializable
            _validate_language,
        ],
        "cover": [
            default_cover_type,
            _validate_cover
        ],
        "save_as": [
            fmt.default_save_as_format,
            _validate_format
        ],
        "use_chapter_title": [
            False,
            _validate_bool
        ],
        "use_compressed_image": [
            False,
            _validate_bool
        ],
    }
    default_conf = {
        x: y for x, (y, _) in confs.items()
    }

    def __init__(self):
        self._data = None
        self._lock = threading.Lock()

        # Load the config
        self._load()

    def _write(self, obj, write_to_path=True):
        """Write config file without lock"""
        data = {}
        
        # Remove unnecessary config
        for d_key, d_value in self.default_conf.items():

            found = False
            for key, value in obj.items():
                if key == d_key:
                    data[d_key] = value
                    found = True
                    break
            
            if not found:
                # Pass the default config
                data[d_key] = d_value

        # Validation tests
        for conf_key, conf_value in obj.items():
            default_value, validator = self.confs[conf_key]

            try:
                validator(conf_value)
            except Exception as e:
                # If somehow config file is messed up
                # because validator is failed to pass the test
                # fallback to default value
                log.debug(
                    f"Config '{conf_key}' (value: {conf_value}) is not passed validator test, " \
                    f"reason: {e}. Falling back to default value"
                )
                data[conf_key] = default_value

        self._data = data

        if config_enabled and write_to_path:
            self.path.write_text(json.dumps(data))

    def _write_default(self):
        self._write(self.default_conf)

    def _load(self):
        # Initialize config
        if config_enabled:
            init()

        if not config_enabled:

            # If config is not enabled
            # use default config
            # useful for passing default arguments in argparse
            if self._data is None:
                self._write_default()

            return

        with self._lock:
            success = False
            err = None
            data = None

            # Very tricky lmao
            for attempt, _ in enumerate(range(5), start=1):
                try:
                    if not self.path.exists():
                        self._write_default()

                    data = json.loads(self.path.read_bytes())
                except json.JSONDecodeError as e:
                    err = e
                    log.error(
                        f'Failed to decode json data from config file = {self.path.resolve()} reason: {err}, retrying... (attempt: {attempt})'
                    )

                    # If somehow failed to decode JSON data, delete it and try it again
                    self.path.unlink(missing_ok=True)
                    continue
                except Exception as e:
                    err = e
                    log.error(
                        f'Failed to load json data from config file = {self.path.resolve()} reason: {err}, retrying... (attempt: {attempt})'
                    )

                else:
                    success = True
                    break

            if not success:
                raise MangaDexException(
                    f"Failed to load config file = {self.path}, " \
                    f"reason: {err}. Make sure you have permission to write & read in that directory"
                )

            # Write new config
            self._write(data)

    def read(self, name):
        self._load()
        return self._data[name]

    def write(self, name, value):
        """Write config file with lock"""
        if not config_enabled:
            raise MangaDexException(
                "Config is not enabled. " \
                "You can enable it by set MANGADEXDL_CONFIG_ENABLED to 1"
            )

        with self._lock:
            obj = self._data.copy()
            obj[name] = value
            self._write(obj)

_conf = _Config()

def set_config_from_cli_opts(args):
    """Set config from cli opts"""
    data = {}
    for key in _conf.default_conf.keys():
        value = getattr(args, key)
        _, validator = _conf.confs[key]
        data[key] = validator(value)
    
    _conf._write(data, write_to_path=False)

def reset_config(name=None):
    """Reset config. If ``name`` is not given, reset all configs"""
    if not name:
        _conf._write(_conf.default_conf)
    else:
        try:
            default_value = _conf.default_conf[name]
        except KeyError:
            raise AttributeError(
                f"type object '{_Config.__name__}' has no attribute '{name}'"
            ) from None

        _conf.write(name, default_value)

def get_all_configs():
    """Return a generator that will yield ``(config_name, config_value)``"""
    return _conf._data.items()

class ConfigProxy:
    def __getattr__(self, name: str):
        try:
            return _conf.read(name)
        except KeyError:
            raise AttributeError(f"type object '{_Config.__name__}' has no attribute '{name}'") from None
    
    def __setattr__(self, name, value):
        try:
            _, validator = _conf.confs[name]
        except KeyError:
            raise AttributeError(f"type object '{_Config.__name__}' has no attribute '{name}'") from None

        try:
            val = validator(value)
        except Exception as e:
            # Provide more details about error
            # Which config triggered this
            err = f"{name}: {str(e)}"
            raise ConfigTypeError(err) from None

        _conf.write(name, val)

# Allow to library to use _Config objects easily
config = ConfigProxy()

class AuthCacheManager:
    path = base_path / 'auth.cache'
    default = {
        "session": {
            "token": None,
            "exp": None
        },
        "refresh": {
            "token": None,
            "exp": None
        }
    }
    fmt_exp_datetime = "%d:%m:%YT%H:%M:%S"
    delay_login_time = 30

    def __init__(self):
        self._data = None
        self._lock = threading.Lock()

        if config_enabled and config.login_cache:
            init()

        # Load the authentication cache
        self._load()

    def _parse_expired_time(self, data):
        """Convert string datetime to :class:`datetime.datetime` object"""
        exp_refresh_token = data['refresh']['exp']
        exp_session_token = data['session']['exp']

        parsed_exp_refresh_token = None
        if exp_refresh_token is not None:
            parsed_exp_refresh_token = datetime.strptime(
                exp_refresh_token,
                self.fmt_exp_datetime
            )

        parsed_exp_session_token = None
        if exp_session_token is not None:
            parsed_exp_session_token = datetime.strptime(
                exp_session_token,
                self.fmt_exp_datetime
            )

        data['refresh']['exp'] = parsed_exp_refresh_token
        data['session']['exp'] = parsed_exp_session_token

    def _read(self):
        if not self.path.exists():
            data = base64.b64encode(json.dumps(self.default).encode())
            self.path.write_bytes(data)

        data = self.path.read_bytes()
        decoded = base64.b64decode(data)
        final_data = json.loads(decoded)
        self._parse_expired_time(final_data)
        return final_data

    def _serialize_exp_time(self, obj):
        """Convert :class:`datetime.datetime` to formatted string"""
        exp_refresh_token = obj['refresh']['exp']
        exp_session_token = obj['session']['exp']

        serialized_exp_refresh_token = None
        if exp_refresh_token is not None:
            serialized_exp_refresh_token = exp_refresh_token.strftime(self.fmt_exp_datetime)

        serialized_exp_session_token = None
        if exp_session_token is not None:
            serialized_exp_session_token = exp_session_token.strftime(self.fmt_exp_datetime)

        obj['refresh']['exp'] = serialized_exp_refresh_token
        obj['session']['exp'] = serialized_exp_session_token

    def _write(self, obj):
        self._serialize_exp_time(obj)
        data = json.dumps(obj).encode()
        self.path.write_bytes(base64.b64encode(data))
        self._parse_expired_time(obj)
        self._data = obj

    def _load(self):
        if not config_enabled or not config.login_cache:
            self._data = self.default.copy()
            return

        success = False
        err = None
        data = None

        for attempt, _ in enumerate(range(5), start=1):
            try:
                data = self._read()
            except binascii.Error as e:
                err = e
                # Failed to decode base64
                log.error(
                    f"Failed to decode auth cache file, reason: {e}. " \
                    "Authentication cache file will be re-created and previous auth cached will be lost. " \
                    f"Recreating... (attempt: {attempt})"
                )
            except json.JSONDecodeError as e:
                err = e
                # Failed to deserialize json
                log.error(
                    f"Failed to deserialize json auth cache file, reason: {e}. " \
                    "Authentication cache file will be re-created and previous auth cached will be lost. " \
                    f"Recreating... (attempt: {attempt})"
                )
            except Exception as e:
                err = e
                # another error
                log.warning(
                    f"Failed to load auth cache file, reason: {e}. " \
                    "Authentication cache file will be re-created and previous auth cached will be lost. " \
                    f"Recreating... (attempt: {attempt})"
                )
            else:
                success = True
                break

            if not success:
                # Try to delete the auth cache file, and try it again
                try:
                    self.path.unlink(missing_ok=True)
                except Exception as e:
                    log.debug(f"Failed to delete auth cache file, reason: {e}")
        if not success:
            exc = MangaDexException(
                f"Failed to load auth cache file ({self.path}), reason: {err}" \
                f"Make sure you have permission to read & write in that directory"
            )
            print("Traceback of last error when loading auth cache file", file=sys.stderr)
            traceback.print_exception(type(err), err, err.__traceback__, file=sys.stderr)

            raise exc

        self._data = data

    def _get_datetime_now(self) -> datetime:
        return datetime.now()

    def _reset_session_token(self):
        data = self._data.copy()

        data['session']['token'] = None
        data['session']['exp'] = None

        self._write(data)

    def _reset_refresh_token(self):
        data = self._data.copy()

        data['refresh']['token'] = None
        data['refresh']['exp'] = None

        self._write(data)

    def get_expiration_time(self, token):
        data = jwt.decode(token, options={'verify_signature': False})
        return datetime.fromtimestamp(data['exp'])

    def get_session_token(self):
        """Union[:class:`str`, ``None``]: A session token for authentication to MangaDex"""
        if not config_enabled or not config.login_cache:
            return

        with self._lock:
            self._load()
            token = self._data['session']['token']
            exp = self._data['session']['exp']
            now = self._get_datetime_now()

            if token is None and exp is None:
                return None

            if exp > now:
                # exp_time must have at least above 30 seconds (30 seconds for re-login)
                exp_time = (exp - now).total_seconds()

                if exp_time <= 30:
                    # The expiration time is less than 30 seconds
                    # Mark is as expired
                    self._reset_session_token()
                    return None

                return token
            else:
                # Token is expired
                self._reset_session_token()
                return None

    def set_session_token(self, token):
        """Write session token to cache file
        
        Parameters
        -----------
        token: :class:`str`
            A valid session token
        """
        if not config_enabled or not config.login_cache:
            return

        with self._lock:
            data = self._data.copy()
            data['session']['token'] = token
            data['session']['exp'] = self.get_expiration_time(token)
            self._write(data)

    def get_refresh_token(self):
        """Union[:class:`str`, ``None``]: A refresh token for renew session token"""
        if not config_enabled or not config.login_cache:
            return

        with self._lock:
            self._load()
            token = self._data['refresh']['token']
            exp = self._data['refresh']['exp']
            now = self._get_datetime_now()

            if token is None and exp is None:
                return None

            if exp > now:
                return token
            # Token is expired
            self._reset_refresh_token()
            return None

    def set_refresh_token(self, token):
        """Write refresh token to cache file
        
        Parameters
        -----------
        token: :class:`str`
            A valid refresh token
        """
        if not config_enabled or not config.login_cache:
            return

        with self._lock:
            data = self._data.copy()
            data['refresh']['token'] = token
            data['refresh']['exp'] = self.get_expiration_time(token)
            self._write(data)

    def purge(self):
        """Purge session and refresh token cache"""
        if not config_enabled or not config.login_cache:
            return

        with self._lock:
            self._reset_session_token()
            self._reset_refresh_token()

login_cache = AuthCacheManager()