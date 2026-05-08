"""Harness for self-documenting the jaato TUI as a user manual.

Three phases:
- inventory: parse source / query daemon for reference catalogs
- walk: drive a live TUI in a fresh tmux window, capture each manifest feature
- build: concatenate sections + render PDF via pandoc

See the workspace README for the CLI surface.
"""
