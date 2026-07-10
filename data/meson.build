desktop_file = configure_file(
  input: 'ring.desktop.in',
  output: 'ring.desktop',
  configuration: {
    'APP_ID': app_id,
    'VERSION': meson.project_version(),
  },
)

install_data(
  desktop_file,
  install_dir: join_paths(get_option('datadir'), 'applications'),
)

metainfo_file = configure_file(
  input: 'ring.metainfo.xml.in',
  output: 'ring.metainfo.xml',
  configuration: {
    'APP_ID': app_id,
    'VERSION': meson.project_version(),
  },
)

install_data(
  metainfo_file,
  install_dir: join_paths(get_option('datadir'), 'metainfo'),
)

install_data(
  'icons/ring.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'),
  rename: app_id + '.svg',
)
