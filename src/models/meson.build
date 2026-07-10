python3 = import('python').find_installation('python3')
python3.install_sources(
  ['__init__.py'] + [f for f in run_command('sh', '-c', 'ls *.py 2>/dev/null || true', check: false).stdout().strip().split('\n') if f],
  subdir: 'qmic/models',
)
