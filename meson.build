project('patchwork', 'c',
  version: '0.1.0',
  license: 'MIT',
  meson_version: '>= 1.0.0',
)

i18n = import('i18n')
gnome = import('gnome')
python = import('python').find_installation('python3')

app_id = 'org.patchwork.Patchwork'

subdir('data')
subdir('src')

install_data('src/main.py', install_dir: get_option('bindir'), rename: 'patchwork')
