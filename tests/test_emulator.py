import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src import GUI


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self.options = kwargs
        self.content = ''
        self.callbacks = []
        self.destroyed = False
    def configure(self, **kwargs): self.options.update(kwargs)
    def pack(self, **kwargs): pass
    def bind(self, *args): pass
    def focus_set(self): pass
    def set(self, *args): pass
    def yview(self, *args): pass
    def see(self, *args): pass
    def geometry(self, *args): pass
    def resizable(self, **kwargs): pass
    def title(self, title): self.window_title = title
    def get(self): return self.content
    def delete(self, *args): self.content = ''
    def insert(self, index, text):
        if index != GUI.tk.END:
            raise AssertionError('Вывод должен добавляться в конец')
        self.content += text
    def after_idle(self, callback): self.callbacks.append(callback)
    def after(self, delay, callback): self.callbacks.append(callback)
    def destroy(self): self.destroyed = True
    def drain(self):
        for _ in range(200):
            if not self.callbacks or self.destroyed:
                return
            self.callbacks.pop(0)()
        raise AssertionError('Скрипт не завершился')


class EmulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_cwd = Path.cwd()
        self.archive = self.root / 'test.zip'
        self.make_zip({'docs/guide.txt': b'guide', 'empty/': b'',
                       'blob.bin': bytes(range(256)), 'space dir/текст.txt': b'text',
                       'a/b/c/file.txt': b'deep'})
        self.vfs = GUI.MemoryVFS.from_zip(self.archive)

    def tearDown(self):
        self.assertEqual(Path.cwd(), self.old_cwd, 'Команды изменили папку реальной ОС')
        self.temp.cleanup()

    def make_zip(self, contents):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, data in contents.items():
                archive.writestr(name, data)

    def script(self, content):
        path = self.root / 'startup.txt'
        path.write_text(content, encoding='utf-8')
        return path

    def app(self, script=None, archive=None):
        args = ['--vfs', str(archive or self.archive)]
        if script:
            args += ['--script', str(script)]
        with patch.multiple(GUI.tk, **{n: FakeWidget for n in ('Frame', 'Label', 'Entry', 'Text', 'Scrollbar')}):
            window = FakeWidget()
            app = GUI.EmulatorApp(window, GUI.read_config(args))
        return window, app

    def command(self, text):
        return GUI.judge(GUI.parser(text), self.vfs)

    def test_binary_base64_roundtrip(self):
        self.assertEqual(self.vfs.files['/blob.bin'], base64.b64encode(bytes(range(256))).decode('ascii'))
        self.assertEqual(self.vfs.read_bytes('/blob.bin'), bytes(range(256)))
        self.assertEqual(self.vfs.read_bytes('/docs/guide.txt'), b'guide')

    def test_memory_operations_continue_without_archive_or_host_access(self):
        self.archive.unlink()
        with patch('builtins.open', side_effect=AssertionError('host read/write')), \
             patch.object(GUI.os, 'listdir', side_effect=AssertionError('host listdir')), \
             patch.object(GUI.os, 'chdir', side_effect=AssertionError('host chdir')):
            self.assertFalse(self.command('ls')['error'])
            self.assertFalse(self.command('cd docs')['error'])
            self.assertEqual(self.command('ls')['output'], 'guide.txt')
            self.assertEqual(self.vfs.read_bytes('guide.txt'), b'guide')
            self.assertFalse(self.command('cd ..')['error'])

    def test_archive_and_disk_unchanged_no_extraction(self):
        before = hashlib.sha256(self.archive.read_bytes()).digest()
        snapshot = list(self.root.rglob('*'))
        with patch.object(zipfile.ZipFile, 'extract', side_effect=AssertionError('extract')), \
             patch.object(zipfile.ZipFile, 'extractall', side_effect=AssertionError('extractall')):
            vfs = GUI.MemoryVFS.from_zip(self.archive)
            vfs.chdir('/a/b/c')
            vfs.listdir()
            vfs.read_bytes('file.txt')
        self.assertEqual(before, hashlib.sha256(self.archive.read_bytes()).digest())
        self.assertEqual(snapshot, list(self.root.rglob('*')))

    def test_implied_dirs_and_empty_dir(self):
        self.assertTrue({'/a', '/a/b', '/a/b/c', '/empty'} <= self.vfs.directories)
        self.assertEqual(self.vfs.listdir('/empty'), [])
        self.assertEqual(self.vfs.listdir('/a'), ['b'])
        self.assertEqual(self.vfs.listdir('/a/b/c'), ['file.txt'])

    def test_empty_zip_valid(self):
        self.make_zip({})
        vfs = GUI.MemoryVFS.from_zip(self.archive)
        self.assertEqual(vfs.directories, {'/'})
        self.assertEqual(vfs.listdir(), [])

    def test_paths_and_root_boundary(self):
        for command in ['cd a/b/c', 'cd ../..', 'cd ./b/c', 'cd /docs', 'cd', 'cd ../../..']:
            self.assertFalse(self.command(command)['error'], command)
        self.assertEqual(self.vfs.cwd, '/')
        self.assertEqual(self.vfs.resolve('///a//b/c/../.'), '/a/b')
        self.assertEqual(self.command('ls /docs')['output'], 'guide.txt')

    def test_host_path_is_not_accessible(self):
        self.assertTrue(self.command(f'ls "{self.root}"')['error'])
        self.assertTrue(self.command(f'cd "{self.root}"')['error'])
        self.assertEqual(self.vfs.cwd, '/')

    def test_file_components_and_missing_components_are_not_normalized_away(self):
        for path in ['/blob.bin/..', '/blob.bin/.', '/blob.bin/', '/missing/../docs']:
            with self.subTest(path=path):
                self.assertTrue(self.command(f'cd {path}')['error'])
        self.assertEqual(self.vfs.cwd, '/')

    def test_parser_spaces_env_home_and_blank(self):
        with patch.dict(os.environ, {'VFS_TEST_DIR': '/space dir'}):
            self.assertEqual(GUI.parser('cd "$VFS_TEST_DIR"')['args'], ['/space dir'])
            self.assertFalse(self.command('cd "$VFS_TEST_DIR"')['error'])
        self.assertEqual(GUI.parser('ls "$HOME"')['args'], [os.environ['HOME']])
        self.assertEqual(GUI.parser('ls ~')['args'], [os.path.expanduser('~')])
        self.assertIsNone(GUI.parser('  ')['command'])
        self.assertFalse(self.command('  ')['error'])

    def test_command_errors_and_exit(self):
        for text in ['unknown', 'ls "bad', 'ls /missing', 'cd /missing',
                     'ls /blob.bin', 'cd /blob.bin', 'ls / /docs', 'cd / /docs',
                     'ls ""', 'cd ""', 'exit extra']:
            with self.subTest(text=text):
                self.assertTrue(self.command(text)['error'])
        self.assertTrue(self.command('exit')['exit_requested'])
        self.assertFalse(self.command('exit extra')['exit_requested'])

    def test_load_errors_missing_format_directory(self):
        invalid = self.root / 'not-a-zip.zip'
        invalid.write_text('plain text')
        for path, message in [(self.root / 'missing.zip', 'файл не найден'),
                              (invalid, 'неверный формат'), (self.root, 'не удалось прочитать')]:
            with self.subTest(path=path), self.assertRaisesRegex(GUI.VFSLoadError, message):
                GUI.MemoryVFS.from_zip(path)

    def test_permission_and_unsupported_compression_errors(self):
        for error in [PermissionError('denied'), NotImplementedError('compression'), RuntimeError('password')]:
            with patch.object(GUI.zipfile, 'ZipFile', side_effect=error):
                with self.assertRaises(GUI.VFSLoadError):
                    GUI.MemoryVFS.from_zip(self.archive)

    def test_corrupt_crc_detected(self):
        marker = b'UNIQUE_BINARY_PAYLOAD'
        self.make_zip({'a.bin': marker})
        data = bytearray(self.archive.read_bytes())
        data[data.index(marker)] ^= 1
        self.archive.write_bytes(data)
        with self.assertRaisesRegex(GUI.VFSLoadError, 'повреждённый ZIP'):
            GUI.MemoryVFS.from_zip(self.archive)

    def test_bad_archive_paths_duplicates_and_conflicts(self):
        for contents in [ {'../escape.txt': b'x'}, {'/absolute.txt': b'x'},
                          {'a\\b.txt': b'x'}, {'a/./b.txt': b'x'},
                          {'a': b'x', 'a/file.txt': b'y'},
                          {'a/file.txt': b'y', 'a': b'x'} ]:
            with self.subTest(contents=contents):
                self.make_zip(contents)
                with self.assertRaises(GUI.VFSLoadError):
                    GUI.MemoryVFS.from_zip(self.archive)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.archive, 'w') as archive:
                archive.writestr('same.txt', b'1')
                archive.writestr('same.txt', b'2')
        with self.assertRaisesRegex(GUI.VFSLoadError, 'повторяющийся'):
            GUI.MemoryVFS.from_zip(self.archive)

    def test_symlinks_rejected(self):
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr(info, b'/etc/passwd')
        with self.assertRaisesRegex(GUI.VFSLoadError, 'ссылки'):
            GUI.MemoryVFS.from_zip(self.archive)

    def test_config_defaults_and_absolute_paths(self):
        config = GUI.read_config([])
        self.assertEqual(Path(config.vfs), PROJECT.resolve() / 'vfs/minimal.zip')
        self.assertIsNone(config.script)
        with patch.dict(os.environ, {'VFS_ARCHIVE': str(self.archive)}):
            config = GUI.read_config(['--vfs', '$VFS_ARCHIVE', '--script', 'startup.txt'])
        self.assertEqual(config.vfs, str(self.archive))
        self.assertEqual(config.script, str(Path.cwd() / 'startup.txt'))
        self.assertIn('--vfs:', GUI.config_text(config))
        self.assertIn('--script:', GUI.config_text(config))

    def test_cli_help_and_invalid_args(self):
        for args, status in [(['--help'], 0), (['--vfs'], 2), (['--typo'], 2)]:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    GUI.read_config(args)
                self.assertEqual(raised.exception.code, status)

    def test_script_stops_at_first_error_with_line_number(self):
        out = []
        results = list(GUI.script_steps(self.script('# comment\n\nls\ncd /missing\nNEVER\n'), out.append, self.vfs))
        self.assertEqual(len(results), 2)
        self.assertIn('строке 4', ''.join(out))
        self.assertNotIn('NEVER', ''.join(out))

    def test_script_exit_stops_following_commands(self):
        out = []
        results = list(GUI.script_steps(self.script('exit\nNEVER\n'), out.append, self.vfs))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['exit_requested'])
        self.assertNotIn('NEVER', ''.join(out))

    def test_script_dialogue_order_and_virtual_prompt(self):
        out = []
        results = list(GUI.script_steps(self.script('cd docs\nls\n'), out.append, self.vfs))
        transcript = ''.join(out)
        self.assertFalse(any(r['error'] for r in results))
        self.assertIn('/docs$ ls', transcript)
        self.assertLess(transcript.index('$ ls'), transcript.index('guide.txt'))

    def test_startup_file_errors_and_bom(self):
        invalid = self.root / 'invalid.txt'
        invalid.write_bytes(b'\xff\xfe')
        for path in [self.root, self.root / 'missing.txt', invalid]:
            out = []
            self.assertEqual(list(GUI.script_steps(path, out.append, self.vfs)), [])
            self.assertIn('Ошибка чтения', ''.join(out))
        result = list(GUI.script_steps(self.script('\ufeffexit\n'), lambda text: None, self.vfs))
        self.assertTrue(result[0]['exit_requested'])

    def test_gui_load_and_manual_commands(self):
        window, app = self.app()
        window.drain()
        self.assertIn('VFS загружена в память', app.output.content)
        self.assertIn(GUI.getpass.getuser(), window.window_title)
        self.assertIn(GUI.socket.gethostname(), window.window_title)
        app.entry.content = 'cd docs'
        app.on_enter()
        self.assertEqual(app.invitation.options['text'], '/docs$ ')
        app.entry.content = 'ls'
        app.on_enter()
        self.assertIn('guide.txt', app.output.content)

    def test_gui_failed_load_no_script_or_host_fallback(self):
        window, app = self.app(self.script('exit\n'), self.root / 'missing.zip')
        window.drain()
        self.assertIsNone(app.vfs)
        self.assertFalse(window.destroyed)
        self.assertIn('Ошибка загрузки VFS', app.output.content)
        app.entry.content = 'ls'
        app.on_enter()
        self.assertIn('ls: VFS не загружена', app.output.content)
        app.entry.content = 'exit'
        app.on_enter()
        self.assertTrue(window.destroyed)

    def test_gui_script_error_and_exit_callbacks(self):
        window, app = self.app(self.script('unknown\nNEVER\n'))
        window.drain()
        self.assertFalse(window.destroyed)
        self.assertEqual(app.entry.options['state'], GUI.tk.NORMAL)
        self.assertNotIn('NEVER', app.output.content)
        window, app = self.app(self.script('exit\nNEVER\n'))
        window.drain()
        self.assertTrue(window.destroyed)
        self.assertNotIn('NEVER', app.output.content)

    def test_gui_script_success_unlocks_input(self):
        window, app = self.app(self.script('ls\ncd docs\nls\n'))
        window.drain()
        self.assertEqual(app.entry.options['state'], GUI.tk.NORMAL)
        self.assertFalse(app.running_script)
        self.assertIn('Стартовый скрипт выполнен.', app.output.content)
        self.assertEqual(app.invitation.options['text'], '/docs$ ')

    def test_sessions_do_not_share_cwd(self):
        second = GUI.MemoryVFS.from_zip(self.archive)
        self.vfs.chdir('/docs')
        self.assertEqual(second.cwd, '/')

    def test_prepared_archive_variants(self):
        minimal = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/minimal.zip')
        self.assertEqual(minimal.listdir(), ['hello.txt'])
        multiple = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/multiple.zip')
        self.assertGreater(len(multiple.files), 1)
        self.assertEqual(multiple.read_bytes('/data/blob.bin'), bytes(range(256)))
        deep = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/deep.zip')
        self.assertEqual(deep.listdir('/level1/level2/level3'), ['note.txt'])

    def test_all_success_examples_and_all_expected_errors(self):
        cases = [('startup_minimal.txt', 'minimal.zip'), ('startup_multiple.txt', 'multiple.zip'),
                 ('startup_deep.txt', 'deep.zip'), ('startup_ok.txt', 'multiple.zip'),
                 ('папка с пробелами/startup.txt', 'multiple.zip')]
        with patch.dict(os.environ, {'VFS_DEMO_DIR': '/docs'}):
            for script, archive in cases:
                vfs = GUI.MemoryVFS.from_zip(PROJECT / 'vfs' / archive)
                out = []
                results = list(GUI.script_steps(PROJECT / 'scripts' / script, out.append, vfs))
                self.assertTrue(results)
                self.assertFalse(any(r['error'] for r in results), (script, ''.join(out)))
            for script in [PROJECT / 'scripts/startup_all.txt', PROJECT / 'scripts/startup_error.txt',
                           *sorted((PROJECT / 'scripts/errors').glob('*.txt'))]:
                vfs = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/deep.zip')
                out = []
                results = list(GUI.script_steps(script, out.append, vfs))
                self.assertTrue(results[-1]['error'], script)
                self.assertEqual(sum(r['error'] for r in results), 1)
                self.assertNotIn('unknown_after_error', ''.join(out))

    def test_linux_launchers_arguments_and_paths(self):
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        log = self.root / 'calls.jsonl'
        executable = fake_bin / 'python3'
        executable.write_text(f'#!{sys.executable}\nimport json, os, sys\nwith open(os.environ["CALL_LOG"], "a") as f:\n    f.write(json.dumps([sys.argv[1:], os.environ.get("VFS_DEMO_DIR")]) + "\\n")\n')
        executable.chmod(0o755)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ['PATH'], CALL_LOG=str(log))
        scripts = sorted((PROJECT / 'scripts').glob('*.sh'))
        self.assertEqual(len(scripts), 13)
        for script in scripts:
            subprocess.run(['bash', '-n', str(script)], check=True)
            subprocess.run(['bash', str(script)], env=env, cwd=self.root, check=True, capture_output=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(calls), 44)
        for args, variable in calls:
            self.assertEqual(len(args), 5)
            self.assertEqual(Path(args[0]), PROJECT / 'src/GUI.py')
            self.assertEqual(args[1], '--vfs')
            self.assertEqual(args[3], '--script')
            if Path(args[4]).name in ('startup_all.txt', 'startup_ok.txt'):
                self.assertEqual(variable, '/docs')
            if '/stage4/' in args[4] or '/stage5/' in args[4]:
                self.assertTrue(Path(args[2]).is_file())
                self.assertTrue(Path(args[4]).is_file())

    def test_uptime_formats_elapsed_and_ignores_wall_clock(self):
        for elapsed, expected in [(0, '00:00:00'), (61.9, '00:01:01'),
                                  (3661.1, '01:01:01'), (90061, '25:01:01')]:
            with self.subTest(elapsed=elapsed), \
                 patch.object(GUI.time, 'monotonic', return_value=GUI.START_TIME + elapsed), \
                 patch.object(GUI.time, 'time', side_effect=AssertionError('wall clock')):
                result = self.command('uptime')
                self.assertFalse(result['error'])
                self.assertEqual(result['output'], f'Время работы эмулятора: {expected}')

    def test_clear_only_erases_display_and_keeps_directory_and_timer(self):
        window, app = self.app()
        window.drain()
        app.entry.content = 'cd docs'
        app.on_enter()
        files_before = dict(app.vfs.files)
        started_before = GUI.START_TIME
        app.output_print('old output')
        app.entry.content = 'clear'
        app.on_enter()
        self.assertEqual(app.output.content, '')
        self.assertEqual(app.output.options['state'], GUI.tk.DISABLED)
        self.assertEqual(app.vfs.cwd, '/docs')
        self.assertEqual(app.vfs.files, files_before)
        self.assertEqual(GUI.START_TIME, started_before)
        self.assertEqual(app.invitation.options['text'], '/docs$ ')
        app.entry.content = 'ls'
        app.on_enter()
        self.assertIn('guide.txt', app.output.content)

    def test_clear_error_does_not_erase_previous_output(self):
        window, app = self.app()
        window.drain()
        app.output_print('keep this text\n')
        app.entry.content = 'clear extra'
        app.on_enter()
        self.assertIn('keep this text', app.output.content)
        self.assertIn('clear: аргументы не поддерживаются', app.output.content)

    def test_new_commands_work_without_vfs(self):
        window, app = self.app(archive=self.root / 'missing.zip')
        window.drain()
        for text in ['clear', 'uptime']:
            app.entry.content = text
            app.on_enter()
        self.assertIsNone(app.vfs)
        self.assertIn('Время работы эмулятора:', app.output.content)
        self.assertFalse(GUI.judge(GUI.parser('clear'), None)['error'])
        self.assertFalse(GUI.judge(GUI.parser('uptime'), None)['error'])

    def test_script_clear_callback_and_following_commands(self):
        out = []
        def clear(): out.clear()
        script = self.script('ls\nclear\nuptime\ncd docs\nls\n')
        result = list(GUI.script_steps(script, out.append, self.vfs, clear))
        transcript = ''.join(out)
        self.assertEqual(len(result), 5)
        self.assertNotIn('blob.bin', transcript)
        self.assertNotIn('$ clear', transcript)
        self.assertIn('Время работы эмулятора:', transcript)
        self.assertIn('/docs$ ls', transcript)
        self.assertFalse(any(r['error'] for r in result))

    def test_invalid_new_commands_stop_script(self):
        for command in ['clear extra', 'uptime extra']:
            with self.subTest(command=command):
                out = []
                result = list(GUI.script_steps(self.script(f'{command}\nNEVER\n'), out.append, self.vfs))
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0]['error'])
                self.assertFalse(result[0]['clear_requested'])
                self.assertNotIn('NEVER', ''.join(out))

    def test_stage4_startup_in_gui(self):
        window, app = self.app(PROJECT / 'scripts/stage4/startup.txt', PROJECT / 'vfs/deep.zip')
        window.drain()
        self.assertFalse(window.destroyed)
        self.assertIn('/docs$ ls', app.output.content)
        self.assertIn('guide.txt', app.output.content)
        self.assertIn('Время работы эмулятора:', app.output.content)
        self.assertIn('Стартовый скрипт остановлен:', app.output.content)
        self.assertNotIn('unknown_after_error', app.output.content)
        self.assertEqual(app.entry.options['state'], GUI.tk.NORMAL)
        self.assertEqual(app.vfs.cwd, '/')

    def test_stage4_error_examples_stop(self):
        for name in ['clear_error.txt', 'uptime_error.txt', 'ls_error.txt', 'cd_file_error.txt']:
            out = []
            vfs = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/deep.zip')
            result = list(GUI.script_steps(PROJECT / 'scripts/stage4' / name, out.append, vfs))
            self.assertTrue(result[-1]['error'], name)
            self.assertNotIn('unknown_after_error', ''.join(out))

    def test_numeric_modes_all_512_values(self):
        for number in range(0o1000):
            for text in [f'{number:03o}', f'{number:04o}']:
                self.assertEqual(GUI.apply_permission_mode(0o755, text), number)
        for bad in ['888', '99', '0o644', '12345', '4755', '64', '-1']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                GUI.apply_permission_mode(0o644, bad)

    def test_symbolic_add_remove_assign_and_sequence(self):
        cases = [
            (0o644, 'u+x', 0o744), (0o640, 'g+w', 0o660),
            (0o640, 'o+r', 0o644), (0o777, 'go-w', 0o755),
            (0o777, 'a=r', 0o444), (0o777, 'u=rw,g=r,o=', 0o640),
            (0o000, 'ug+rw,o+r', 0o664), (0o755, 'a=', 0o000),
            (0o644, 'a+x,u-x', 0o655), (0o644, 'u+', 0o644),
        ]
        for current, mode, expected in cases:
            with self.subTest(mode=mode):
                self.assertEqual(GUI.apply_permission_mode(current, mode), expected)
        for bad in ['u+q', 'u+x,g+q', '', 'u+r,', '+x', 'g=u', 'a+X']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                GUI.apply_permission_mode(0o644, bad)

    def test_permissions_defaults_and_archive_metadata(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            info = zipfile.ZipInfo('file')
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o640) << 16
            archive.writestr(info, b'data')
            directory = zipfile.ZipInfo('directory/')
            directory.create_system = 3
            directory.external_attr = (stat.S_IFDIR | 0o711) << 16
            archive.writestr(directory, b'')
            zero = zipfile.ZipInfo('zero')
            zero.create_system = 3
            zero.external_attr = stat.S_IFREG << 16
            archive.writestr(zero, b'zero')
            dos = zipfile.ZipInfo('implicit/dos')
            dos.create_system = 0
            dos.external_attr = 32
            archive.writestr(dos, b'dos')
        vfs = GUI.MemoryVFS.from_zip(self.archive)
        self.assertEqual(vfs.permissions, {'/': 0o755, '/file': 0o640,
                                         '/directory': 0o711, '/zero': 0,
                                         '/implicit': 0o755, '/implicit/dos': 0o644})

    def test_chmod_file_directory_relative_spaces_and_multiple(self):
        self.vfs.chdir('/docs')
        self.assertFalse(self.command('chmod 644 guide.txt')['error'])
        self.assertFalse(self.command('chmod u+x ./guide.txt')['error'])
        self.assertEqual(self.vfs.permissions['/docs/guide.txt'], 0o744)
        self.assertFalse(self.command('chmod 700 /docs')['error'])
        self.assertEqual(self.vfs.permissions['/docs'], 0o700)
        self.assertFalse(self.command('chmod 600 /blob.bin "/space dir/текст.txt"')['error'])
        self.assertEqual(self.vfs.permissions['/blob.bin'], 0o600)
        self.assertEqual(self.vfs.permissions['/space dir/текст.txt'], 0o600)
        self.assertEqual(self.vfs.cwd, '/docs')

    def test_recursive_changes_descendants_not_sibling_prefix(self):
        self.vfs.add_directory('/ab')
        before = dict(self.vfs.permissions)
        self.assertFalse(self.command('chmod -R 700 /a')['error'])
        for item, mode in self.vfs.permissions.items():
            if item == '/a' or item.startswith('/a/'):
                self.assertEqual(mode, 0o700)
            else:
                self.assertEqual(mode, before[item])
        self.assertFalse(self.command('chmod --recursive a+r /a')['error'])
        self.assertEqual(self.vfs.permissions['/a/b/c/file.txt'], 0o744)

    def test_nonrecursive_directory_and_recursive_file(self):
        before = self.vfs.permissions['/docs/guide.txt']
        self.command('chmod 700 /docs')
        self.assertEqual(self.vfs.permissions['/docs/guide.txt'], before)
        self.assertFalse(self.command('chmod -R 640 /blob.bin')['error'])
        self.assertEqual(self.vfs.permissions['/blob.bin'], 0o640)

    def test_recursive_root_and_overlapping_targets(self):
        self.command('chmod -R 600 /')
        self.assertTrue(all(mode == 0o600 for mode in self.vfs.permissions.values()))
        self.command('chmod -R u+x /a /a/b')
        self.assertEqual(self.vfs.permissions['/a/b/c/file.txt'], 0o700)
        self.assertEqual(self.vfs.permissions['/blob.bin'], 0o600)

    def test_chmod_never_writes_to_host_archive_or_content(self):
        before_bytes = self.archive.read_bytes()
        before_mode = self.archive.stat().st_mode
        before_files = dict(self.vfs.files)
        with patch.object(GUI.os, 'chmod', side_effect=AssertionError('host chmod')), \
             patch('builtins.open', side_effect=AssertionError('disk access')), \
             patch.object(GUI.zipfile, 'ZipFile', side_effect=AssertionError('archive reopened')):
            self.vfs.chmod('000', ['/blob.bin', '/docs'], recursive=True)
        self.assertEqual(self.archive.read_bytes(), before_bytes)
        self.assertEqual(self.archive.stat().st_mode, before_mode)
        self.assertEqual(self.vfs.files, before_files)
        self.assertEqual(self.vfs.read_bytes('/blob.bin'), bytes(range(256)))

    def test_reloading_resets_permission_changes(self):
        baseline = dict(self.vfs.permissions)
        self.command('chmod -R 000 /')
        new_vfs = GUI.MemoryVFS.from_zip(self.archive)
        self.assertEqual(new_vfs.permissions, baseline)

    def test_chmod_errors_are_atomic(self):
        before = dict(self.vfs.permissions)
        for command in ['chmod', 'chmod 644', 'chmod -R', 'chmod 888 /blob.bin',
                        'chmod u+x,g+q /blob.bin', 'chmod 600 /blob.bin /missing',
                        'chmod 644 /blob.bin/child', 'chmod 644 ""', 'chmod -R 755 /missing']:
            with self.subTest(command=command):
                result = self.command(command)
                self.assertTrue(result['error'])
                self.assertEqual(before, self.vfs.permissions)
        self.assertTrue(GUI.judge(GUI.parser('chmod 644 /file'), None)['error'])

    def test_ls_l_reports_changes_and_plain_ls_stays_same(self):
        before = self.command('ls')['output']
        self.command('chmod 640 /docs/guide.txt')
        self.assertEqual(self.command('ls -l /docs/guide.txt')['output'], '-rw-r----- 0640 guide.txt')
        self.command('chmod 750 /docs')
        self.assertIn('drwxr-x--- 0750 docs', self.command('ls -l /')['output'])
        self.assertEqual(self.command('ls')['output'], before)
        self.command('cd docs')
        self.assertEqual(self.command('ls -l')['output'], '-rw-r----- 0640 guide.txt')
        self.assertFalse(self.command('ls -l /empty')['error'])
        self.assertEqual(self.command('ls -l /empty')['output'], '')
        self.assertTrue(self.command('ls -l /missing')['error'])
        self.assertTrue(self.command('ls -l / /docs')['error'])

    def test_gui_manual_chmod_and_ls_l(self):
        window, app = self.app()
        window.drain()
        for command in ['chmod 640 /blob.bin', 'ls -l /blob.bin']:
            app.entry.content = command
            app.on_enter()
        self.assertEqual(app.vfs.permissions['/blob.bin'], 0o640)
        self.assertIn('-rw-r----- 0640 blob.bin', app.output.content)

    def test_stage5_startup_and_error_examples(self):
        window, app = self.app(PROJECT / 'scripts/stage5/startup.txt', PROJECT / 'vfs/deep.zip')
        window.drain()
        self.assertFalse(window.destroyed)
        self.assertIn('Стартовый скрипт выполнен.', app.output.content)
        self.assertEqual(app.vfs.permissions['/data/blob.bin'], 0o444)
        self.assertEqual(app.vfs.permissions['/docs/guide.txt'], 0o640)
        self.assertEqual(app.vfs.permissions['/level1/level2/level3/note.txt'], 0o754)
        self.assertEqual(app.entry.options['state'], GUI.tk.NORMAL)
        cases = list((PROJECT / 'scripts/stage5/errors').glob('*.txt'))
        self.assertEqual(len(cases), 9)
        for script in cases:
            out = []
            vfs = GUI.MemoryVFS.from_zip(PROJECT / 'vfs/deep.zip')
            before = dict(vfs.permissions)
            results = list(GUI.script_steps(script, out.append, vfs))
            self.assertTrue(results[-1]['error'], script)
            self.assertNotIn('unknown_after_error', ''.join(out))
            self.assertEqual(vfs.permissions, before)

    def test_root_launcher_help_from_another_directory(self):
        result = subprocess.run(
            ['bash', str(PROJECT / 'run.sh'), '--help'], cwd=self.root,
            capture_output=True, text=True, check=True,
        )
        self.assertIn('--vfs', result.stdout)
        self.assertIn('--script', result.stdout)

    def test_root_launcher_forwards_paths_with_spaces(self):
        fake_bin = self.root / 'launcher-bin'
        fake_bin.mkdir()
        capture = self.root / 'launcher.json'
        executable = fake_bin / 'python3'
        executable.write_text(
            f'#!{sys.executable}\nimport json, os, sys\n'
            'with open(os.environ["CAPTURE"], "w") as f:\n'
            '    json.dump([sys.argv[1:], os.getcwd()], f)\n'
        )
        executable.chmod(0o755)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ['PATH'], CAPTURE=str(capture))
        subprocess.run(
            ['bash', str(PROJECT / 'run.sh'), '--vfs', '/tmp/path with spaces.zip',
             '--script', '/tmp/скрипт с пробелами.txt'],
            env=env, cwd=self.root, check=True,
        )
        args, cwd = json.loads(capture.read_text())
        self.assertEqual(args, [str(PROJECT / 'src/GUI.py'), '--vfs',
                               '/tmp/path with spaces.zip', '--script',
                               '/tmp/скрипт с пробелами.txt'])
        self.assertEqual(cwd, str(PROJECT))


if __name__ == '__main__':
    unittest.main()
