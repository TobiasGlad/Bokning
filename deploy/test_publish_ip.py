import unittest
from publish_ip import apache_config, private_settings


class IPDeploymentTests(unittest.TestCase):
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
