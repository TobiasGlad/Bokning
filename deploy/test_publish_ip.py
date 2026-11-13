import unittest
from publish_ip import apache_config, private_settings, inject_ip_routes


class IPDeploymentTests(unittest.TestCase):
    def test_ip_virtualhosts_take_priority_over_existing_catchall(self):
        original = '''<VirtualHost 192.0.2.10:80 [2001:db8::1]:80>
    ServerAlias 192.0.2.10
    RewriteRule ^ https://192.0.2.10%{REQUEST_URI} [R=308,L,NE]
    ProxyPass / http://127.0.0.1:3010/
</VirtualHost>
<VirtualHost 192.0.2.10:443>
    SSLEngine On
    SSLCertificateFile /existing/cert.pem
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass / http://127.0.0.1:3010/
</VirtualHost>
<VirtualHost 192.0.2.11:443>
    ProxyPass / http://127.0.0.1:9000/
</VirtualHost>'''
        updated, count, https = inject_ip_routes(original, '192.0.2.10')
        self.assertEqual(count, 2)
        self.assertTrue(https)
        blocks = updated.split('</VirtualHost>')
        for block in blocks[:2]:
            self.assertLess(block.index('Include '), block.index('ProxyPass /'))
        self.assertNotIn('Include ', blocks[2])
        self.assertIn('SSLCertificateFile /existing/cert.pem', updated)
        self.assertIn('RewriteRule ^ https://192.0.2.10%{REQUEST_URI}', updated)
        again, count, https = inject_ip_routes(updated, '192.0.2.10')
        self.assertEqual(again, updated)
        self.assertEqual(count, 0)
        self.assertTrue(https)

    def test_no_trailing_slash_is_also_proxied(self):
        config = apache_config()
        self.assertIn('ProxyPassMatch "^/bokning$" "http://127.0.0.1:8010/bokning/"', config)

    def test_existing_https_enables_secure_cookie_and_proxy_support(self):
        values = private_settings({'SECRET_KEY': 'unchanged'}, '192.0.2.10', https=True)
        self.assertEqual(values['PUBLIC_ORIGIN'], 'https://192.0.2.10')
        self.assertEqual(values['SECURE_COOKIES'], 'true')
        self.assertEqual(values['TRUST_PROXY_HTTPS'], 'true')
        self.assertEqual(values['SSL_REDIRECT'], 'true')

    def test_prefix_route_keeps_private_data_unreachable(self):
        config = apache_config()
        self.assertIn('ProxyPass /bokning/ http://127.0.0.1:8010/bokning/', config)
        self.assertIn('ProxyPass /bokning/static/ !', config)
        self.assertNotIn('/root/', '\n'.join(line for line in config.splitlines() if not line.startswith('#')))
        self.assertNotIn('DocumentRoot', config)
        self.assertNotIn('VirtualHost', '\n'.join(line for line in config.splitlines() if not line.startswith('#')))

    def test_http_settings_preserve_secrets_and_existing_hosts(self):
        original = {'SECRET_KEY': 'test-key', 'TOKEN_ENCRYPTION_KEY': 'test-token-key', 'ALLOWED_HOSTS': 'old.example.invalid'}
        values = private_settings(original, '192.0.2.10')
        self.assertEqual(values['SECRET_KEY'], original['SECRET_KEY'])
        self.assertEqual(values['TOKEN_ENCRYPTION_KEY'], original['TOKEN_ENCRYPTION_KEY'])
        self.assertEqual(values['PUBLIC_ORIGIN'], 'http://192.0.2.10')
        self.assertIn('old.example.invalid', values['ALLOWED_HOSTS'])
        self.assertIn('192.0.2.10', values['ALLOWED_HOSTS'])
        self.assertEqual(values['SECURE_COOKIES'], 'false')
        self.assertEqual(original['ALLOWED_HOSTS'], 'old.example.invalid')


if __name__ == '__main__':
    unittest.main()
