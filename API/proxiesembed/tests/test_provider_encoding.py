"""Régressions des en-têtes CDN, sans démarrer le serveur ni charger ses secrets."""

import ast
import asyncio
import base64
import binascii
import hashlib
import logging
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp import ClientTimeout, web

PROXY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROXY_ROOT))
from uqload_utils import (
    extract_uqload_media_url,
    extract_uqload_subtitles,
    get_uqload_site_origin,
    normalize_uqload_embed_url,
    parse_allowed_uqload_url,
)


def load_proxy_headers():
    tree = ast.parse((PROXY_ROOT / 'server.py').read_text(encoding='utf-8-sig'))
    proxy_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ProxyServer')
    methods = {
        '_prepare_headers', 'fsvid_proxy_handler', 'vidzy_proxy_handler', 'uqload_proxy_handler',
        'fsvid_extract_handler', 'vidzy_extract_handler', '_is_fsvid_vidzy_embed_url',
        '_extract_uqload_media_url', '_extract_uqload_media', '_validate_uqload_url',
        '_extract_m3u8_url',
    }
    proxy_class.body = [
        node for node in proxy_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods
        or isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.startswith('RE_') for target in node.targets
        )
    ]
    constants = [
        node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.startswith(('FSVID_VIDZY_', 'PROVIDER_MEDIA_'))
            for target in node.targets
        )
    ]
    module = ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        *constants, proxy_class,
    ], type_ignores=[])
    namespace = {
        're': re, 'urlparse': urlparse, 'urljoin': urljoin,
        'base64': base64, 'binascii': binascii,
        'get_uqload_site_origin': get_uqload_site_origin,
        'parse_allowed_uqload_url': parse_allowed_uqload_url,
        'normalize_uqload_embed_url': normalize_uqload_embed_url,
        'extract_uqload_media_url': extract_uqload_media_url,
        'extract_uqload_subtitles': extract_uqload_subtitles,
        'asyncio': asyncio, 'aiohttp': aiohttp, 'ClientTimeout': ClientTimeout,
        'web': web, 'hashlib': hashlib,
        '_signed_service_url': lambda route, url: url,
        'logger': logging.getLogger(__name__),
    }
    exec(compile(ast.fix_missing_locations(module), 'server.py', 'exec'), namespace)
    return namespace['ProxyServer']()


class ProviderEncodingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proxy = load_proxy_headers()

    def assert_identity_with_browser_tokens(self, headers):
        # Vidzy refuse les requêtes sans « zstd ». q=0 interdit la compression
        # correspondante : aiohttp 3.11 et les clients Android restent compatibles.
        self.assertEqual(
            headers.get('Accept-Encoding'),
            'identity, gzip;q=0, deflate;q=0, br;q=0, zstd;q=0',
        )

    async def test_dedicated_and_generic_relays_use_the_same_encoding(self):
        proxy = self.proxy
        proxy._service_proxy = AsyncMock()
        proxy._service_proxy_via_random_socks = AsyncMock()
        for provider, host, origin in [
            ('fsvid', 'r1.fsvid.lol', 'https://fsvid.lol'),
            ('vidzy', 'u14.vidzy.cc', 'https://vidzy.org'),
            ('uqload', 'strm4.uqload.vc', 'https://uqload.vc'),
            ('uqload', 'strm1.uqload.bz', 'https://uqload.bz'),
        ]:
            with self.subTest(provider=provider, host=host):
                url = f'https://{host}/hls/master.m3u8?t=example&s=123&i=0.0'
                request = SimpleNamespace(query={'url': url}, headers={}, method='GET')
                await getattr(proxy, f'{provider}_proxy_handler')(request)
                relay = proxy._service_proxy if provider == 'uqload' else proxy._service_proxy_via_random_socks
                dedicated = relay.call_args.args[2]
                generic = proxy._prepare_headers(url, request)
                for headers in (dedicated, generic):
                    self.assert_identity_with_browser_tokens(headers)
                    self.assertEqual(headers['Origin'], origin)
                    self.assertEqual(headers['Referer'], f'{origin}/')

    async def test_extraction_leaves_compression_negotiation_to_aiohttp(self):
        proxy = self.proxy
        session = MagicMock()
        media = 'https://strm4.uqload.vc/hls/master.m3u8?t=example'
        session.request.return_value.__aenter__.return_value = SimpleNamespace(
            status=200, text=AsyncMock(return_value=f'<script>var sources=["{media}"];</script>'),
        )
        proxy.sessions = {'normal': session, 'no_ssl': session}
        proxy._require_internal = lambda request: None
        proxy._check_vip = AsyncMock(return_value=True)
        proxy._resolve_fsvid_vidzy_m3u8 = AsyncMock(return_value=media)
        for provider, host in [('fsvid', 'fsvid.lol'), ('vidzy', 'vidzy.org'), ('uqload', 'uqload.vc')]:
            with self.subTest(provider=provider):
                session.request.reset_mock()
                url = f'https://{host}/embed-example.html'
                if provider == 'uqload':
                    self.assertEqual(await proxy._extract_uqload_media_url(url), media)
                else:
                    setattr(proxy, f'{provider}_cache', SimpleNamespace(get=lambda key: None, set=lambda *args: None))
                    response = await getattr(proxy, f'{provider}_extract_handler')(SimpleNamespace(query={'url': url}))
                    self.assertEqual(response.status, 200)
                headers = session.request.call_args.kwargs['headers']
                self.assertNotIn('Accept-Encoding', headers)

    def test_rolling_xor_survives_a_misread_width_measurement(self):
        # Lecteur Vidzy d'octobre 2026 : la largeur mesurée est celle d'un
        # enfant à 50 % d'un parent en `calc(1in + 60px)`, soit 78 px et non
        # 156. Une graine mal relue doit quand même retrouver la vraie URL,
        # jamais le leurre `troll`.
        embed = 'https://vidzy.cc/embed-example.html'
        media = 'https://v6.vidzy.cc/hls2/01/00064/,example_n,.urlset/master.m3u8?t=token&s=1'
        host_sum = sum(map(ord, 'vidzy.cc')) & 255
        encrypted = bytes(
            ord(char) ^ ((0x3d + index * 89 + host_sum + 78) & 255)
            for index, char in enumerate(media)
        )[::-1]
        payload = base64.b64encode(encrypted).decode()
        script = (
            'sources: [{src: (function(s){var h=(location&&location.hostname)||"",H=0;'
            'for(var j=0;j<h.length;j++){H=(H+h.charCodeAt(j))&255;}var BC=0;try{'
            'var _p=document.createElement("div");_p.style.cssText="position:absolute;width:calc(1in + 60px)";'
            'var _ch=document.createElement("div");_ch.style.cssText="height:1px;width:50%";'
            '_p.appendChild(_ch);BC=_ch.offsetWidth|0;}catch(e){}'
            'var b=atob(s),a=b.split("").reverse().join(""),r="";'
            'for(var i=0;i<a.length;i++){var kk=(0x3d+i*89+H+BC)&255;'
            'r+=String.fromCharCode(a.charCodeAt(i)^kk)}'
            'return /^https?:/.test(r)?r:"https://v6.vidzy.cc/troll/master.m3u8"})'
            f'("{payload}"), type: "application/x-mpegURL"}}]'
        )
        self.assertEqual(self.proxy._extract_m3u8_url(script, embed), media)


if __name__ == '__main__':
    unittest.main()
