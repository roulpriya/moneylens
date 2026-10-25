# Bundled website and report fonts

These unmodified Latin variable WOFF2 files are vendored from
`@fontsource-variable/dm-sans@5.3.0` and
`@fontsource-variable/newsreader@5.3.0` (Fontsource / Google Fonts).

`OFL.txt` retains both fonts' copyright and SIL Open Font License notices.
The Bun report compiler includes the notices and embeds the font bytes in the
compiled HTML. Vite serves the same source fonts as local website assets.
Installed skills need only the compiled template; they do not need these source
files, a font service, or a JavaScript build runtime.
