# Overview

The sketchup plugin exposes a unix socket (Windows 11 or OSX required) and a plugin is able to subsribe to model updates to support live syncing.


# Development

Run tests:

```
uv run pytest tests/integration -v
```

To build sketchup plugin:

```bash
bundle install
bundle exec ruby package.rb
# → Created: dist/sketchup-link-1.0.0.rbz
```