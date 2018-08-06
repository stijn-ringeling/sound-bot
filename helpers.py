import logging
import urllib

import requests

api_ref = "https://discordapp.com/api/v6"
api_options = {"v": 6, "encoding": "json"}
_name = "darkPy"
_level = logging.DEBUG

logger = logging.getLogger(_name)
logger.setLevel(_level)
ch = logging.StreamHandler()
ch.setLevel(_level)

formattter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

ch.setFormatter(formattter)
logger.addHandler(ch)

def get_gateway():
    r = requests.get(api_ref +"/gateway")
    return r.json()['url'] + "?" + urllib.parse.urlencode(api_options)

def setup_logger():
    return logger
