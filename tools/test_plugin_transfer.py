import unittest

from dock_probe import ProtocolError
from plugin_transfer import PLUGIN, digest, install


class Files:
    def __init__(self):
        self.original = b"3GX$0002" + b"a" * 1024
        self.files = {PLUGIN: self.original}
        self.fail_commit = False
        self.corrupt_stage = False
        self.corrupt_commit = False
        self.changed = False

    def read(self, name):
        data = self.files[name]
        if self.corrupt_stage and "-stage-" in name:
            return b"broken"
        if self.corrupt_commit and name == PLUGIN and self.changed:
            return b"broken"
        return data

    def write_new(self, name, data):
        if name in self.files:
            raise ProtocolError("File exists")
        self.files[name] = data

    def rename(self, source, target):
        if self.fail_commit and "-stage-" in source and target == PLUGIN:
            raise ProtocolError("Commit failed")
        if target in self.files:
            raise ProtocolError("Target exists")
        self.files[target] = self.files.pop(source)
        if target == PLUGIN and "-stage-" in source:
            self.changed = True


class PluginTransferTests(unittest.TestCase):
    def setUp(self):
        self.fs = Files()
        self.new = b"3GX$0002" + b"b" * 1024
        self.expected = digest(self.fs.original)

    def test_install_retains_original_backup(self):
        result = install(self.fs, self.new, self.expected, "test")
        self.assertEqual(self.fs.files[PLUGIN], self.new)
        self.assertEqual(self.fs.files[result["remote_backup"]], self.fs.original)

    def test_changed_original_is_not_overwritten(self):
        with self.assertRaises(ProtocolError):
            install(self.fs, self.new, "wrong", "test")
        self.assertEqual(self.fs.files, {PLUGIN: self.fs.original})

    def test_corrupt_stage_does_not_replace_original(self):
        self.fs.corrupt_stage = True
        with self.assertRaises(ProtocolError):
            install(self.fs, self.new, self.expected, "test")
        self.assertEqual(self.fs.files[PLUGIN], self.fs.original)

    def test_failed_commit_restores_original(self):
        self.fs.fail_commit = True
        with self.assertRaises(ProtocolError):
            install(self.fs, self.new, self.expected, "test")
        self.assertEqual(self.fs.files[PLUGIN], self.fs.original)

    def test_failed_final_verification_restores_original(self):
        self.fs.corrupt_commit = True
        with self.assertRaises(ProtocolError):
            install(self.fs, self.new, self.expected, "test")
        self.assertEqual(self.fs.files[PLUGIN], self.fs.original)


if __name__ == "__main__":
    unittest.main()
