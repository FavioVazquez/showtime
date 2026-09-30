# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue or discussion. Use GitHub's
private vulnerability reporting: open the repository's **Security** tab and choose **Report a
vulnerability** (https://github.com/FavioVazquez/showtime/security/advisories/new). The report
and the conversation about it stay private until an advisory is published.

A useful report says what is affected (command, file or tool), the version (`showtime version`), the
operating system, the steps to reproduce, and what an attacker gains. You get a reply in the
advisory thread; the fix is released as a new version and the advisory credits you unless you ask
otherwise.

## Scope

- The `showtime` command line (the skill's `bin/showtime` launchers, `lib/`, `scripts/`) and the
  stable `<SHOWTIME_HOME>/bin/showtime` command it installs.
- The MCP server (`skills/showtime/mcp/`, also run through the `@faviovazquez/showtime-mcp` npm package).
- The local servers: the preview server (`showtime preview`, and the one `check`, `render` and `snap`
  start) and the studio board server, which listen on 127.0.0.1.
- The installers: `showtime setup` (what it downloads and how it verifies it), `showtime install`
  (the files it writes into agent folders) and the plugin and extension manifests in this repository.

Out of scope: problems in third-party tools showtime installs (Chrome, ffmpeg, Node, Python packages,
models); report those upstream. showtime renders the pages and runs the scene files you give it, with
your permissions, like any build tool: running untrusted project files is not a vulnerability in showtime
unless it escapes what that command is documented to do.

## Supported versions

Only the latest 0.x release gets security fixes. Update to it before reporting when you can.
