desktop_file = configure_file(
  input: 'qmic.desktop.in',
  output: 'qmic.desktop',
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
  input: 'qmic.metainfo.xml.in',
  output: 'qmic.metainfo.xml',
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
  'icons/qmic.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'),
  rename: app_id + '.svg',
)
