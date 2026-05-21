"""
Tests for src/anonymizer.py — PromptAnonymizer.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.anonymizer import PromptAnonymizer


class TestIPv4(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_single_ip_replaced(self):
        result = self.a.anonymize("Server at 192.168.1.10 is down.")
        self.assertNotIn("192.168.1.10", result)
        self.assertIn("[IP_1]", result)

    def test_multiple_ips_get_distinct_placeholders(self):
        result = self.a.anonymize("Primary: 10.0.0.1, Secondary: 10.0.0.2")
        self.assertIn("[IP_1]", result)
        self.assertIn("[IP_2]", result)
        self.assertNotIn("10.0.0.1", result)
        self.assertNotIn("10.0.0.2", result)

    def test_same_ip_reuses_placeholder(self):
        r1 = self.a.anonymize("Host: 172.16.0.5")
        r2 = self.a.anonymize("Same host: 172.16.0.5")
        # Both should use [IP_1]
        self.assertEqual(r1.count("[IP_1]"), 1)
        self.assertEqual(r2.count("[IP_1]"), 1)
        self.assertEqual(self.a.mapping_count, 1)

    def test_loopback_127_replaced(self):
        result = self.a.anonymize("Listening on 127.0.0.1:8080")
        self.assertIn("[IP_1]", result)
        self.assertNotIn("127.0.0.1", result)

    def test_invalid_ip_not_replaced(self):
        # 999.x.x.x is not a valid IP — should not match
        result = self.a.anonymize("Value: 999.0.0.1")
        self.assertNotIn("[IP_1]", result)


class TestIPv6(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_loopback_replaced(self):
        result = self.a.anonymize("Bound to ::1 port 443")
        self.assertNotIn("::1", result)
        self.assertIn("[IP6_1]", result)

    def test_full_ipv6_replaced(self):
        addr = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        result = self.a.anonymize(f"Address: {addr}")
        self.assertNotIn(addr, result)
        self.assertIn("[IP6_1]", result)


class TestMAC(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_mac_replaced(self):
        result = self.a.anonymize("Interface eth0  HWaddr aa:bb:cc:dd:ee:ff")
        self.assertNotIn("aa:bb:cc:dd:ee:ff", result)
        self.assertIn("[MAC_1]", result)

    def test_uppercase_mac_replaced(self):
        result = self.a.anonymize("MAC: AA:BB:CC:11:22:33")
        self.assertNotIn("AA:BB:CC:11:22:33", result)
        self.assertIn("[MAC_1]", result)


class TestEmail(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_email_replaced(self):
        result = self.a.anonymize("Contact admin@example.com for help.")
        self.assertNotIn("admin@example.com", result)
        self.assertIn("[EMAIL_1]", result)

    def test_email_with_subdomain(self):
        result = self.a.anonymize("Send to user@mail.company.org")
        self.assertNotIn("user@mail.company.org", result)
        self.assertIn("[EMAIL_1]", result)


class TestAPIKey(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_openai_key_replaced(self):
        result = self.a.anonymize("key = sk-abcdefghijklmnopqrstuvwxyz123456")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", result)
        self.assertIn("[API_KEY_1]", result)

    def test_anthropic_key_replaced(self):
        result = self.a.anonymize("ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXXXXXXXXXX")
        self.assertNotIn("sk-ant-api03-XXXXXXXXXXXXXXXXXXXX", result)
        self.assertIn("[API_KEY_1]", result)


class TestSeeding(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()
        self.a.seed(username="user", hostname="myserver")

    def test_username_replaced(self):
        result = self.a.anonymize("Logged in as user")
        self.assertNotIn("user", result)
        self.assertIn("[USER_1]", result)

    def test_hostname_replaced(self):
        result = self.a.anonymize("Host myserver is up.")
        self.assertNotIn("myserver", result)
        self.assertIn("[HOST_1]", result)

    def test_username_in_path_replaced(self):
        result = self.a.anonymize("Working dir: /home/user/projects/neo")
        self.assertNotIn("user", result)

    def test_username_not_replaced_as_substring(self):
        # "user" inside "dashboard" should NOT be replaced
        result = self.a.anonymize("Open the dashboard now")
        self.assertIn("dashboard", result)
        self.assertNotIn("[USER_1]board", result)


class TestPathAnonymization(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()

    def test_home_path_replaced(self):
        result = self.a.anonymize("CWD: /home/alice/gitrepos/project")
        self.assertNotIn("/home/alice/gitrepos/project", result)
        self.assertIn("[PATH_1]", result)

    def test_users_path_replaced(self):
        result = self.a.anonymize("File at /Users/bob/Documents/report.pdf")
        self.assertNotIn("/Users/bob/Documents/report.pdf", result)
        self.assertIn("[PATH_1]", result)

    def test_root_path_replaced(self):
        result = self.a.anonymize("Config: /root/.ssh/authorized_keys")
        self.assertNotIn("/root/.ssh/authorized_keys", result)
        self.assertIn("[PATH_1]", result)

    def test_system_path_not_replaced(self):
        # Standard system paths should pass through unchanged
        result = self.a.anonymize("Binary at /usr/bin/python3")
        self.assertIn("/usr/bin/python3", result)
        self.assertNotIn("[PATH_1]", result)

    def test_etc_path_not_replaced(self):
        result = self.a.anonymize("Config at /etc/nginx/nginx.conf")
        self.assertIn("/etc/nginx/nginx.conf", result)


class TestDeanonymization(unittest.TestCase):
    def setUp(self):
        self.a = PromptAnonymizer()
        self.a.seed(username="user", hostname="myserver")

    def test_deanonymize_restores_ip(self):
        anonymized = self.a.anonymize("Connect to 10.0.0.5")
        restored = self.a.deanonymize(anonymized)
        self.assertIn("10.0.0.5", restored)
        self.assertNotIn("[IP_1]", restored)

    def test_deanonymize_restores_hostname(self):
        anonymized = self.a.anonymize("Host: myserver")
        restored = self.a.deanonymize(anonymized)
        self.assertIn("myserver", restored)
        self.assertNotIn("[HOST_1]", restored)

    def test_roundtrip(self):
        original = "ssh user@10.0.0.5 -i /home/user/.ssh/id_rsa"
        anonymized = self.a.anonymize(original)
        self.assertNotIn("user", anonymized)
        self.assertNotIn("10.0.0.5", anonymized)
        restored = self.a.deanonymize(anonymized)
        self.assertIn("10.0.0.5", restored)


class TestConsistency(unittest.TestCase):
    def test_same_value_same_placeholder_across_calls(self):
        a = PromptAnonymizer()
        r1 = a.anonymize("First mention: 192.168.0.1")
        r2 = a.anonymize("Second mention: 192.168.0.1")
        self.assertIn("[IP_1]", r1)
        self.assertIn("[IP_1]", r2)
        self.assertEqual(a.mapping_count, 1)

    def test_reset_clears_mapping(self):
        a = PromptAnonymizer()
        a.anonymize("IP: 10.1.1.1")
        self.assertEqual(a.mapping_count, 1)
        a.reset()
        self.assertEqual(a.mapping_count, 0)
        # After reset, same value gets a fresh placeholder (still _1)
        r = a.anonymize("IP: 10.1.1.1")
        self.assertIn("[IP_1]", r)

    def test_no_double_anonymisation(self):
        a = PromptAnonymizer()
        text = "IP: 1.2.3.4"
        once = a.anonymize(text)
        twice = a.anonymize(once)
        # Applying twice should not produce [IP_1_1] or similar
        self.assertNotIn("[IP_1_1]", twice)
        self.assertEqual(once, twice)


class TestMixedContent(unittest.TestCase):
    def test_real_world_ssh_output(self):
        a = PromptAnonymizer()
        a.seed(username="admin", hostname="prod-server-01")
        text = (
            "Warning: prod-server-01 (192.168.10.5) last login: admin "
            "from 203.0.113.42 via ssh. "
            "Home: /home/admin/apps"
        )
        result = a.anonymize(text)
        self.assertNotIn("prod-server-01", result)
        self.assertNotIn("192.168.10.5", result)
        self.assertNotIn("admin", result)
        self.assertNotIn("203.0.113.42", result)
        self.assertNotIn("/home/admin/apps", result)


if __name__ == "__main__":
    unittest.main()
