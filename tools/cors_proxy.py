# (c) 2025 Neeraj Sharma
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
# pip install python-dotenv requests
# ```


# A simple CORS proxy, which is companion to some of the tools available
# on https://napp.pro. You can inspect the requests and responses for any
# security concerns.
#
# This proxy supports the following services and endpoints:
#
# 1. Yacy server:
#    - HTTP GET /Crawler_p.html
# 2. Meilisearch:
#    - HTTP GET, POST - /indexes
#    - HTTP GET, POST, PUT, PATCH, DELETE - /indexes/
#    - HTTP GET - /version, /health, /stats
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
from io import BytesIO

# Load environment variables from .env file
load_dotenv()

PROXY_PORT = int(os.getenv('PROXY_PORT', 8882))
PROXY_HOST = os.getenv('PROXY_HOST', 'localhost')

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class ProxyHandler(BaseHTTPRequestHandler):
    allowed_origins = os.getenv('CORS_ALLOWED_ORIGINS_STR').split(',')
    yacy_target_server = os.getenv('YACY_HOST_URL')
    yacy_username = os.getenv('YACY_USERNAME')
    yacy_password = os.getenv('YACY_PASSWORD')
    meilisearch_target_server = os.getenv('MEILISEARCH_HOST_URL')
    meilisearch_api_key = os.getenv('MEILISEARCH_API_KEY')

    def log_message(self, format, *args):
        logging.info("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def do_OPTIONS(self):
        """
        See https://fetch.spec.whatwg.org/#http-cors-protocol
        """
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            # self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS,POST,PUT,PATCH,DELETE")
            # self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
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
                self._handle_yacy_api(origin, path, 'get')
            elif path in ['/version', '/health', '/stats'] or path == '/indexes' or path.startswith('/indexes?') or path.startswith('/indexes/'):
                # NOTE: ['/version', '/health', '/stats'] are generic, but required by meiliadmin web-tool to work.
                # We can either think about using a separate proxy just for meilisearch or route these generic api endpoints
                # just to meilisearch server.
                self._handle_meilisearch_request(origin, path, 'get')
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

    def do_PUT(self):
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            path = self.path
            content_length = int(self.headers['Content-Length'])
            payload = self.rfile.read(content_length)

            if path.startswith('/indexes/'):
                self._handle_meilisearch_request(origin, path, 'put', payload)
            else:
                logging.error('Invalid path')
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            logging.error(f'Rejecting PUT for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            path = self.path
            content_length = int(self.headers['Content-Length'])
            payload = self.rfile.read(content_length)

            if path == '/indexes' or path.startswith('/indexes/'):
                self._handle_meilisearch_request(origin, path, 'post', payload)
            else:
                logging.error('Invalid path')
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            logging.error(f'Rejecting POST for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def do_PATCH(self):
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            path = self.path
            content_length = int(self.headers['Content-Length'])
            payload = self.rfile.read(content_length)

            if path.startswith('/indexes/'):
                self._handle_meilisearch_request(origin, path, 'patch', payload)
            else:
                logging.error('Invalid path')
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            logging.error(f'Rejecting PATCH for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def do_DELETE(self):
        origin = self.headers.get('Origin')
        if origin in ProxyHandler.allowed_origins:
            path = self.path

            if path.startswith('/indexes/'):
                self._handle_meilisearch_request(origin, path, 'delete')
            else:
                logging.error('Invalid path')
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
        else:
            logging.error(f'Rejecting DELETE for origin = {origin}')
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')

    def _handle_meilisearch_request(self, origin, path, http_request, payload=None):
        """

        See https://www.meilisearch.com/docs/reference/api/settings#stop-words
        """
        target_url = f'{ProxyHandler.meilisearch_target_server}{path}'
        logging.info(f'Forwarding HTTP {http_request} request to {target_url}')
        api_key_patched = False
        for k in self.headers.keys():
            if k.lower() == 'authorization':
                self.headers[k] = f'Bearer {ProxyHandler.meilisearch_api_key}'
                api_key_patched = True
                break
        if not api_key_patched:
            self.headers['authorization'] = f'Bearer {ProxyHandler.meilisearch_api_key}'

        self._handle_generic_forward(target_url, http_request, payload)

    def _handle_yacy_api(self, origin, path, http_request, payload=None):
        """
        Yacy uses HTTP Digest authentication.

        See https://github.com/yacy/yacy_search_server/issues/354
        See https://yacy.net/api/crawler/
        See https://www.digitalocean.com/community/tutorials/how-to-configure-yacy-as-an-alternative-search-engine-or-site-search-tool
        """
        target_url = f'{ProxyHandler.yacy_target_server}{path}'
        auth=HTTPDigestAuth(ProxyHandler.yacy_username,
                            ProxyHandler.yacy_password)
        self._handle_generic_forward(target_url, http_request, payload, auth)

    def _handle_generic_forward(self, target_url, http_request, payload=None, auth=None):
        logging.info(f'Forwarding request to {target_url}')

        try:
            if http_request == 'get':
                response = requests.get(target_url,
                                        stream=True,
                                        headers=self.headers,
                                        auth=auth)
            elif http_request == 'post':
                response = requests.post(target_url,
                                         stream=True,
                                         data=payload,
                                         headers=self.headers,
                                         auth=auth)
            elif http_request == 'put':
                response = requests.put(target_url,
                                        stream=True,
                                        data=payload,
                                        headers=self.headers,
                                        auth=auth)
            elif http_request == 'patch':
                response = requests.patch(target_url,
                                          stream=True,
                                        data=payload,
                                        headers=self.headers,
                                        auth=auth)
            elif http_request == 'delete':
                response = requests.delete(target_url,
                                           stream=True,
                                           headers=self.headers,
                                           auth=auth)
            else:
                response = requests.get(target_url,
                                        stream=True,
                                        headers=self.headers,
                                        auth=auth)

            self.send_response(200)
            for k, v in response.headers.items():
                lower_key = k.lower()
                lower_value = v.lower()
                if lower_key == 'access-control-allow-origin':
                    self.send_header('Access-Control-Allow-Origin', '*')
                    # self.send_header('Access-Control-Allow-Origin', origin)
                elif lower_key in ['server', 'date']:
                    # note that self.send_response(200) sends server and date header
                    # already, so skip those
                    pass
                elif lower_key == 'transfer-encoding' and lower_value == 'chunked':
                    # chunked transfer encoding response is unsupported at present
                    pass
                else:
                    # logging.debug(f'header: {k} = {v}')
                    self.send_header(k, v)
            self.end_headers()
            # handle case when Content-Encoding = gzip, so decode_content=False
            # and stream=True when making request earlier.
            buffer = BytesIO()
            for chunk in response.raw.stream(2**8, decode_content=False):
                buffer.write(chunk)
            buffer.seek(0)
            self.wfile.write(buffer.read())
            # response_data = response.content
            # logging.debug(f'Response from {target_url}: {response_data}')
            # self.wfile.write(response_data)
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