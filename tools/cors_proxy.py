# LICENSE: MIT

# Dependencies
#
# ```console
# python -m venv venv
# ```
#
# Windows:
# ```console
# venv\Scripts\activate
# ```
#
# GNU/Linux or Mac OSX
# ```console
# source venv/bin/activate
# ```
#
# ```console
# pip install python-dotenv
# ```


# A simple CORS proxy, which is companion to some of the tools available
# on https://napp.pro. You can inspect the requests and responses for any
# security concerns.
#
# This proxy supports the following services and endpoints:
#
# 1. Yacy server:
#    - HTTP GET /Crawler_p.html
#
#
# Note: You should also use browser developer inspect tools to look at
# any of the web tools available on https://napp.pro to ensure that
# everything is in order and no data leak happens on that website.
#
# Note: The best approach is to have proxy, so that you dont have
# to save password or access keys (for some of the tools on https://napp.pro)
# within browser local cache. Even that can be risky. Although,
# https://napp.pro do not save any of user settings or content, even then
# having proxy in between is always a good idea and store keys there.
#

from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from dotenv import load_dotenv
import os
import requests
from requests.auth import HTTPDigestAuth

# Load environment variables from .env file
load_dotenv()

PROXY_PORT = int(os.getenv('PROXY_PORT', 8882))
PROXY_HOST = os.getenv('PROXY_HOST', 'localhost')

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class ProxyHandler(BaseHTTPRequestHandler):
    allowed_origins = os.getenv('CORS_ALLOWED_ORIGINS').split(',')
    yacy_target_server = os.getenv('YACY_HOST_URL')
    yacy_username = os.getenv('YACY_USERNAME')
    yacy_password = os.getenv('YACY_PASSWORD')

    def log_message(self, format, *args):
        logging.info("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def do_OPTIONS(self):
        """
        See https://fetch.spec.whatwg.org/#http-cors-protocol
        """
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            self.send_response(204)
            #self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header('Access-Control-Allow-Origin', origin)
            #self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS,POST,PUT")
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers, Authorization')
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
        else:
            logging.error(f'Rejecting OPTIONS for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def do_GET(self):
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            path = self.path

            if path.startswith('/Crawler_p.html'):
                self._handle_yacy_crawler_p_api(origin, path)
            else:
                logging.error('Invalid path')
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            logging.error(f'Rejecting GET for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def _handle_yacy_crawler_p_api(self, origin, path):
        """
        Yacy uses HTTP Digest authentication.

        See https://github.com/yacy/yacy_search_server/issues/354
        See https://yacy.net/api/crawler/
        See https://www.digitalocean.com/community/tutorials/how-to-configure-yacy-as-an-alternative-search-engine-or-site-search-tool
        """
        target_url = f'{ProxyHandler.yacy_target_server}{path}'
        logging.info(f'Forwarding request to {target_url}')

        try:
            response = requests.get(target_url,
                                        headers=self.headers,
                                        auth=HTTPDigestAuth(ProxyHandler.yacy_username,
                                                            ProxyHandler.yacy_password))
            response_data = response.content
            logging.info(f'Response from {target_url}: {response_data}')
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', origin)
            self.end_headers()
            self.wfile.write(response_data)
        except Exception as e:
            logging.error(f'Error forwarding request: {e}')
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'Internal Server Error')

def run(server_class=HTTPServer, handler_class=ProxyHandler, port=PROXY_PORT, host=PROXY_HOST):
    server_address = (host, port)
    httpd = server_class(server_address, handler_class)
    logging.info(f'Starting proxy server on host {host}, port {port}')
    httpd.serve_forever()

if __name__ == '__main__':
    run()