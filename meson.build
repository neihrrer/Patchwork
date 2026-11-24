project('patchwork',
  version: '0.1.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 1.0.0',
)

app_id = 'org.patchwork.Patchwork'

subdir('data')
subdir('src')

install_data('src/main.py', install_dir: get_option('bindir'), rename: 'patchwork')
