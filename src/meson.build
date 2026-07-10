blueprint_compiler = find_program('blueprint-compiler', required: true)

# Compile blueprints to XML
window_ui = custom_target(
  'compile-window-ui',
  input: 'resources/window.blp',
  output: 'window.ui',
  command: [blueprint_compiler, 'compile', '@INPUT@', '--output', '@OUTPUT@'],
  build_by_default: true,
)

shortcuts_ui = custom_target(
  'compile-shortcuts-ui',
  input: 'resources/shortcuts.blp',
  output: 'shortcuts.ui',
  command: [blueprint_compiler, 'compile', '@INPUT@', '--output', '@OUTPUT@'],
  build_by_default: true,
)

# Install Python package
python3 = import('python').find_installation('python3')

python_sources = [
  '__init__.py',
  'main.py',
  'application.py',
  'window.py',
  'style.css',
]

foreach src : python_sources
  python3.install_sources(
    src,
    subdir: 'qmic',
  )
endforeach

# Install subpackages
subdir('models')
subdir('gmic')
subdir('imagemagick')
subdir('nodes')
subdir('widgets')
subdir('processing')

# Install UI files
ui_dir = join_paths(get_option('datadir'), 'qmic')
install_data(window_ui, install_dir: ui_dir)
install_data(shortcuts_ui, install_dir: ui_dir)
